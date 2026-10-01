from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from aiogram.exceptions import TelegramForbiddenError

from src.delivery import send_event
from src.sentry.parser import ParsedEvent, parse


def _ev(**kw):
    base = dict(resource="issue", action="created", project_slug="p", project_ref_id=None,
                environment=None, title="t", web_url=None, issue_id="123")
    base.update(kw)
    return ParsedEvent(**base)


async def test_delivery_recorded_as_sent(repos):
    await repos.routes.add("p", None, 10)
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=555))
    await send_event(bot, repos, _ev())
    [row] = await repos.deliveries.recent_for_chat(10)
    assert row["status"] == "sent" and row["tg_message_id"] == 555 and row["issue_id"] == "123"
    assert await repos.deliveries.last_message_for_issue(10, "123") == 555


async def test_delivery_recorded_as_failed(repos):
    await repos.routes.add("p", None, 10)
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=TelegramForbiddenError(method=MagicMock(), message="bot was kicked"))
    await send_event(bot, repos, _ev())
    [row] = await repos.deliveries.recent_for_chat(10)
    assert row["status"] == "failed" and "kicked" in row["error"]
    assert await repos.deliveries.last_message_for_issue(10, "123") is None
    counts = await repos.deliveries.count_by_status(datetime.now(timezone.utc) - timedelta(hours=1))
    assert counts == {"failed": 1}


def test_issue_id_extraction():
    ev = parse({"action": "created", "data": {"issue": {"id": "987"}}}, "issue")
    assert ev.issue_id == "987"
    ev = parse({"action": "created", "data": {"error": {
        "issue_url": "https://sentry.io/api/0/organizations/o/issues/4242/"}}}, "error")
    assert ev.issue_id == "4242"
    ev = parse({"action": "triggered", "data": {"event": {
        "web_url": "https://sentry.io/organizations/o/issues/77/events/abc/"}}}, "event_alert")
    assert ev.issue_id == "77"
