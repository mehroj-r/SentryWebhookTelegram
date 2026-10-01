import datetime as dt
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from aiogram.types import Chat, Message, Update

from src.chat_settings import parse_quiet_range, parse_timezone, quiet_until
from src.delivery import flush_digests, send_event
from src.sentry.parser import ParsedEvent
from tests.bot_harness import ADMIN, GROUP, Harness


def _ev(**kw):
    base = dict(resource="issue", action="created", project_slug="p", project_ref_id=None,
                environment=None, title="t", web_url=None, issue_id="1", extra={"level": "error"})
    base.update(kw)
    return ParsedEvent(**base)


def test_parsers():
    assert parse_timezone("Asia/Tashkent") == "Asia/Tashkent"
    assert parse_timezone("Mars/Olympus") is None
    assert parse_quiet_range("22:00-08:00") == ("22:00", "08:00")
    assert parse_quiet_range("9:30-17:00") == ("09:30", "17:00")
    assert parse_quiet_range("22:00") is None and parse_quiet_range("22:00-22:00") is None


def test_quiet_until_wrapping_midnight_in_timezone():
    prefs = {"timezone": "Asia/Tashkent", "quiet_start": "22:00", "quiet_end": "08:00"}  # UTC+5
    # 23:00 local = 18:00 UTC → quiet until 08:00 local = 03:00 UTC next day
    now = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)
    assert quiet_until(prefs, now) == datetime(2026, 10, 2, 3, 0, tzinfo=timezone.utc)
    # 02:00 local = 21:00 UTC previous day → until 03:00 UTC same UTC day
    now = datetime(2026, 10, 1, 21, 0, tzinfo=timezone.utc)
    assert quiet_until(prefs, now) == datetime(2026, 10, 2, 3, 0, tzinfo=timezone.utc)
    # 12:00 local → not quiet
    assert quiet_until(prefs, datetime(2026, 10, 1, 7, 0, tzinfo=timezone.utc)) is None
    assert quiet_until(None) is None and quiet_until({"quiet_start": "22:00"}) is None


async def test_quiet_hours_hold_then_flush_but_fatal_bypasses(repos):
    await repos.routes.add("p", None, 10)
    now_local = datetime.now(timezone.utc)
    start = (now_local - timedelta(hours=1)).strftime("%H:%M")
    end = (now_local + timedelta(hours=1)).strftime("%H:%M")
    await repos.chat_settings.update(10, timezone="UTC", quiet_start=start, quiet_end=end)

    bot = MagicMock(); bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    await send_event(bot, repos, _ev())
    bot.send_message.assert_not_awaited()
    [row] = await repos.deliveries.recent_for_chat(10)
    assert row["status"] == "digest" and "quiet hours" in row["error"]

    await send_event(bot, repos, _ev(issue_id="2", extra={"level": "fatal"}))
    bot.send_message.assert_awaited_once()

    assert await flush_digests(bot, repos) == 0  # still quiet
    assert await flush_digests(bot, repos, force=True) == 1
    assert "Digest" in bot.send_message.call_args.args[1]


async def test_topic_route_sends_into_thread(repos):
    await repos.routes.add("p", None, 10, thread_id=77)
    bot = MagicMock(); bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    await send_event(bot, repos, _ev())
    assert bot.send_message.call_args.kwargs["message_thread_id"] == 77
    [row] = await repos.deliveries.recent_for_chat(10)
    assert row["thread_id"] == 77


async def test_route_created_inside_topic_captures_thread(repos):
    h = Harness(repos)
    text = "/add_route backend"
    msg = Message(
        message_id=5, date=dt.datetime.now(), chat=GROUP, from_user=ADMIN, text=text,
        message_thread_id=321, is_topic_message=True,
        entities=[{"type": "bot_command", "offset": 0, "length": len(text)}],
    )
    await h.dp.feed_update(h.bot, Update(update_id=900, message=msg))
    [r] = await repos.routes.list_for_chat(GROUP.id)
    assert r["thread_id"] == 321
    await h.command("/routes")
    assert "🧵" in h.session.sent[-1].reply_markup.inline_keyboard[0][0].text


async def test_settings_commands(repos):
    h = Harness(repos)
    await h.command("/settings")
    assert "UTC" in h.session.last_text
    await h.command("/tz Europe/Berlin")
    assert "Europe/Berlin" in h.session.last_text
    await h.command("/tz Nowhere/Land")
    assert "Unknown timezone" in h.session.last_text
    await h.command("/quiet 22:00-08:00")
    prefs = await repos.chat_settings.get(GROUP.id)
    assert prefs["quiet_start"] == "22:00" and prefs["timezone"] == "Europe/Berlin"
    await h.command("/quiet off")
    assert (await repos.chat_settings.get(GROUP.id))["quiet_start"] is None
