from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramForbiddenError

from src.config import settings
from src.delivery import retry_failed, send_event
from src.sentry.parser import ParsedEvent
from tests.bot_harness import GROUP, OTHER, Harness

TOKEN = "admin-token-for-retry"


def _ev():
    return ParsedEvent(resource="issue", action="created", project_slug="p", project_ref_id=None,
                       environment=None, title="Boom", web_url=None, issue_id="1")


def _kicked():
    return TelegramForbiddenError(method=MagicMock(), message="bot was kicked")


async def _fail(repos, chat_id, title="Boom", text="<b>Boom</b>", thread_id=None):
    return await repos.deliveries.record(
        chat_id=chat_id, resource="issue", action="created", project="p", environment=None,
        issue_id="1", title=title, status="failed", error="forbidden", text=text, thread_id=thread_id,
    )


async def test_failed_delivery_keeps_text_and_can_be_retried(repos):
    await repos.routes.add("p", None, 10, thread_id=4)
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=_kicked())
    await send_event(bot, repos, _ev())
    [row] = await repos.deliveries.retryable(10)
    assert row["text"] and "Boom" in row["text"]

    bot.send_message = AsyncMock(return_value=MagicMock(message_id=77))
    assert await retry_failed(bot, repos, 10) == (1, 0)
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["message_thread_id"] == 4
    statuses = [r["status"] for r in await repos.deliveries.recent_for_chat(10)]
    assert sorted(statuses) == ["retried", "sent"]
    assert await repos.deliveries.retryable(10) == []
    # threading picks up the successful retry
    assert await repos.deliveries.last_message_for_issue(10, "1") == 77


async def test_retry_that_fails_again_stays_retryable_once(repos):
    await _fail(repos, 10)
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=_kicked())
    assert await retry_failed(bot, repos, 10) == (0, 1)
    [again] = await repos.deliveries.retryable(10)
    assert again["text"] == "<b>Boom</b>"
    assert await repos.deliveries.count_retryable() == 1


async def test_retry_scope_and_limit(repos):
    for i in range(3):
        await _fail(repos, 10, title=f"t{i}")
    await _fail(repos, 20)
    await _fail(repos, 10, text=None)  # nothing stored: not retryable
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    assert await retry_failed(bot, repos, 10, limit=2) == (2, 0)
    # newest two, sent oldest first
    assert [c.args[1] for c in bot.send_message.await_args_list] == ["<b>Boom</b>"] * 2
    assert [r["title"] for r in await repos.deliveries.retryable(10)] == ["t0"]
    assert await repos.deliveries.count_retryable() == 2  # t0 + chat 20


# ── /retry_failed ──────────────────────────────────────────────────────────────


@pytest.fixture
def h(repos):
    return Harness(repos)


async def test_command(h, repos):
    await h.command("/retry_failed")
    assert "Nothing to retry" in h.session.last_text

    await _fail(repos, GROUP.id, text="<b>resent</b>")
    await _fail(repos, 999)  # other chat untouched
    await h.command("/retry_failed 0")
    assert "Usage" in h.session.last_text
    await h.command("/retry_failed", user=OTHER)
    assert "not allowed" in h.session.last_text

    await h.command("/retry_failed")
    assert any(m.text == "<b>resent</b>" for m in h.session.sent)
    assert "1 sent" in h.session.last_text
    assert await repos.deliveries.retryable(GROUP.id) == []
    assert len(await repos.deliveries.retryable(999)) == 1
    [entry] = await repos.audit.recent_for_chat(GROUP.id)
    assert entry["action"] == "retry_failed"


# ── admin page ─────────────────────────────────────────────────────────────────


@pytest.fixture
async def client(repos, monkeypatch):
    import asyncio

    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from src.admin_web import register_admin
    from src.web import BG_TASKS_KEY, BOT_KEY, QUEUE_KEY, REPOS_KEY

    monkeypatch.setattr(settings, "admin_token", TOKEN)
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=5))
    app = web.Application()
    app[REPOS_KEY] = repos
    app[BOT_KEY] = bot
    app[QUEUE_KEY] = asyncio.Queue()
    app[BG_TASKS_KEY] = set()
    register_admin(app)
    async with TestClient(TestServer(app)) as c:
        yield c


async def test_admin_retry_button(client, repos):
    html = await (await client.get("/admin", params={"token": TOKEN})).text()
    assert "/admin/retry" not in html

    await _fail(repos, 10)
    await _fail(repos, 20)
    html = await (await client.get("/admin", params={"token": TOKEN})).text()
    assert "Retry failed deliveries (2 of 2)" in html
    assert f'name="token" value="{TOKEN}"' in html

    resp = await client.post("/admin/retry", data={"token": "wrong"}, allow_redirects=False)
    assert resp.status == 401
    resp = await client.post("/admin/retry", params={"token": TOKEN}, allow_redirects=False)
    assert resp.status == 401  # query token not accepted for POST
    assert await repos.deliveries.count_retryable() == 2

    resp = await client.post("/admin/retry", data={"token": TOKEN}, allow_redirects=False)
    assert resp.status == 303
    assert resp.headers["Location"].startswith("/admin?status=sent&retried=")
    assert await repos.deliveries.count_retryable() == 0

    html = await (await client.get(resp.headers["Location"])).text()
    assert "Retry finished: 2 sent, 0 failed" in html
