from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from src.delivery import _resolve_chats, send_event
from src.filters import describe_filters, event_level, parse_duration, skip_reason
from src.sentry.parser import ParsedEvent


def _ev(**kw):
    base = dict(resource="issue", action="created", project_slug="p", project_ref_id=None,
                environment=None, title="t", web_url=None, extra={"level": "warning"})
    base.update(kw)
    return ParsedEvent(**base)


def test_level_filter():
    assert skip_reason(_ev(), {"min_level": "error"}) is not None
    assert skip_reason(_ev(extra={"level": "error"}), {"min_level": "error"}) is None
    assert skip_reason(_ev(extra={"level": "critical"}), {"min_level": "fatal"}) is None
    # no level → passes
    assert skip_reason(_ev(resource="comment", extra={}), {"min_level": "fatal"}) is None
    # metric alert maps action to level
    assert event_level(_ev(resource="metric_alert", action="critical", extra={})) == "error"
    assert skip_reason(_ev(resource="metric_alert", action="warning", extra={}), {"min_level": "error"})


def test_action_filter():
    assert skip_reason(_ev(action="assigned"), {"actions": "created,resolved"})
    assert skip_reason(_ev(action="resolved"), {"actions": "created,resolved"}) is None


def test_mute_filter_handles_naive_and_aware():
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    assert "muted" in skip_reason(_ev(), {"muted_until": future})
    assert "muted" in skip_reason(_ev(), {"muted_until": future.replace(tzinfo=None)})
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    assert skip_reason(_ev(), {"muted_until": past}) is None
    assert "🔇" in describe_filters({"muted_until": future})
    assert describe_filters({"min_level": "error", "actions": "created"}) == " [≥error] [created]"


def test_parse_duration():
    assert parse_duration("30m") == timedelta(minutes=30)
    assert parse_duration("2h") == timedelta(hours=2)
    assert parse_duration("1d") == timedelta(days=1)
    assert parse_duration("soon") is None


async def test_filters_applied_per_chat_and_recorded(repos):
    await repos.routes.add("p", None, 1)
    await repos.routes.add("p", None, 2)
    assert await repos.routes.set_filters(2, "p", min_level="error") == 1
    assert await _resolve_chats(repos, _ev()) == [1]

    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    await send_event(bot, repos, _ev())
    bot.send_message.assert_awaited_once()
    [skipped] = await repos.deliveries.recent_for_chat(2)
    assert skipped["status"] == "skipped" and "below" in skipped["error"]


async def test_chat_matching_via_several_routes_delivers_if_any_passes(repos):
    await repos.routes.add("p", "prod", 1)
    await repos.routes.add("p", "staging", 1)
    # mute only the prod route; an env-less issue event matches both
    async with repos.routes._sessionmaker() as s:
        from sqlalchemy import update
        from src.db.models import Route
        await s.execute(update(Route).where(Route.environment == "prod")
                        .values(muted_until=datetime.now(timezone.utc) + timedelta(hours=1)))
        await s.commit()
    assert await _resolve_chats(repos, _ev()) == [1]


async def test_set_filters_scoped(repos):
    await repos.routes.add("a", None, 1)
    await repos.routes.add("b", None, 1)
    assert await repos.routes.set_filters(1, None, actions="created") == 2
    assert await repos.routes.set_filters(1, "a", min_level=None, actions=None) == 1
    routes = {r["project"]: r for r in await repos.routes.list_for_chat(1)}
    assert routes["a"]["actions"] is None and routes["b"]["actions"] == "created"
