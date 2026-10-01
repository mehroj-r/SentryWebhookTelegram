from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from src.delivery import flush_digests, send_event
from src.sentry.formatters import format_digest
from src.sentry.parser import ParsedEvent
from tests.bot_harness import GROUP, Harness


def _ev(**kw):
    base = dict(resource="issue", action="created", project_slug="p", project_ref_id=None,
                environment="prod", title="Boom", web_url="https://s.io/issues/1/", issue_id="1",
                extra={"level": "error"})
    base.update(kw)
    return ParsedEvent(**base)


async def test_digest_route_parks_then_flushes(repos):
    await repos.routes.add("p", None, 10)
    await repos.routes.set_filters(10, "p", digest_minutes=60)
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))

    await send_event(bot, repos, _ev())
    await send_event(bot, repos, _ev())
    await send_event(bot, repos, _ev(issue_id="2", title="Other", extra={"level": "warning"}))
    bot.send_message.assert_not_awaited()
    assert await repos.digests.pending_count(10) == 3
    rows = await repos.deliveries.recent_for_chat(10)
    assert {r["status"] for r in rows} == {"digest"}

    assert await flush_digests(bot, repos) == 0  # period not elapsed
    assert await flush_digests(bot, repos, force=True) == 1
    text = bot.send_message.call_args.args[1]
    assert "3 events across 2 issues" in text and "×2" in text and "Other" in text
    assert await repos.digests.pending_count(10) == 0
    assert (await repos.deliveries.recent_for_chat(10))[0]["resource"] == "digest"


async def test_due_detection_uses_route_period(repos):
    await repos.routes.add("p", None, 10)
    await repos.routes.set_filters(10, "p", digest_minutes=5)
    bot = MagicMock(); bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    await send_event(bot, repos, _ev())
    assert await repos.digests.due_chats(datetime.now(timezone.utc) + timedelta(minutes=4)) == []
    assert await repos.digests.due_chats(datetime.now(timezone.utc) + timedelta(minutes=6)) == [10]


async def test_instant_route_beats_digest_route_for_same_chat(repos):
    await repos.routes.add("p", "prod", 10)   # instant
    await repos.routes.add("p", None, 10)     # digest
    await repos.routes.set_filters(10, None, digest_minutes=30)
    # make only the env-less route a digest: re-set prod route to instant
    async with repos.routes._sessionmaker() as s:
        from sqlalchemy import update
        from src.db.models import Route
        await s.execute(update(Route).where(Route.environment == "prod").values(digest_minutes=None))
        await s.commit()
    bot = MagicMock(); bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    await send_event(bot, repos, _ev(environment=None))  # matches both routes
    bot.send_message.assert_awaited_once()
    assert await repos.digests.pending_count(10) == 0


def test_format_digest_groups_and_clamps():
    items = [{"project": "p", "issue_id": str(i % 3), "title": f"T{i % 3}", "level": "error",
              "action": "created", "environment": None, "web_url": None} for i in range(9)]
    text = format_digest(items)
    assert "9 events across 3 issues" in text and text.count("×3") == 3


async def test_digest_command(repos):
    h = Harness(repos)
    await h.command("/add_route backend")
    await h.command("/digest backend 60")
    [r] = await repos.routes.list_for_chat(GROUP.id)
    assert r["digest_minutes"] == 60
    await h.command("/routes")
    assert "📰60m" in h.session.sent[-1].reply_markup.inline_keyboard[0][0].text
    await h.command("/digest all off")
    [r] = await repos.routes.list_for_chat(GROUP.id)
    assert r["digest_minutes"] is None
    await h.command("/digest backend 99999")
    assert "between 1 and 1440" in h.session.last_text
