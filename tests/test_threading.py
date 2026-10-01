from unittest.mock import AsyncMock, MagicMock

from src.delivery import send_event
from src.sentry.formatters import TELEGRAM_MAX_LEN, append_footer, status_footer
from src.sentry.parser import ParsedEvent


def _ev(**kw):
    base = dict(resource="issue", action="created", project_slug="p", project_ref_id=None,
                environment=None, title="t", web_url=None, issue_id="123")
    base.update(kw)
    return ParsedEvent(**base)


def _bot(first_id=100):
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=[MagicMock(message_id=first_id), MagicMock(message_id=first_id + 1)])
    bot.edit_message_text = AsyncMock()
    return bot


async def test_follow_up_replies_and_stamps_original(repos):
    await repos.routes.add("p", None, 10)
    bot = _bot()
    await send_event(bot, repos, _ev())
    assert bot.send_message.call_args.kwargs["reply_parameters"] is None

    await send_event(bot, repos, _ev(action="resolved", actor="Alice"))
    reply = bot.send_message.call_args.kwargs["reply_parameters"]
    assert reply.message_id == 100 and reply.allow_sending_without_reply is True

    bot.edit_message_text.assert_awaited_once()
    edited = bot.edit_message_text.call_args
    assert edited.kwargs["message_id"] == 100
    assert "RESOLVED" in edited.args[0] and "Alice" in edited.args[0]
    # stored text updated so the next footer stacks on the stamped version
    row = await repos.deliveries.last_for_issue(10, "123")
    assert row["tg_message_id"] == 101  # latest post is the reply
    rows = await repos.deliveries.recent_for_chat(10)
    original = [r for r in rows if r["tg_message_id"] == 100][0]
    assert "RESOLVED" in original["text"]


async def test_different_issue_is_not_threaded(repos):
    await repos.routes.add("p", None, 10)
    bot = _bot()
    await send_event(bot, repos, _ev(issue_id="1"))
    await send_event(bot, repos, _ev(issue_id="2"))
    assert bot.send_message.call_args.kwargs["reply_parameters"] is None
    bot.edit_message_text.assert_not_awaited()


async def test_edit_failure_does_not_break_delivery(repos):
    await repos.routes.add("p", None, 10)
    bot = _bot()
    bot.edit_message_text = AsyncMock(side_effect=RuntimeError("message can't be edited"))
    await send_event(bot, repos, _ev())
    await send_event(bot, repos, _ev(action="resolved"))
    rows = await repos.deliveries.recent_for_chat(10)
    assert [r["status"] for r in rows] == ["sent", "sent"]


def test_footer_helpers():
    assert status_footer(_ev(action="created")) is None
    assert status_footer(_ev(resource="error", action="resolved")) is None
    footer = status_footer(_ev(action="assigned", actor="Bob", extra={"assigned_to": "Team <A>"}))
    assert "ASSIGNED" in footer and "Team &lt;A&gt;" in footer and "by Bob" in footer
    assert append_footer("x" * (TELEGRAM_MAX_LEN - 2), "footer") is None
    assert append_footer("hello", "footer") == "hello\nfooter"
