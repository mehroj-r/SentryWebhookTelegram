import pytest
from aiogram.types import Chat, User

from src.bot.keyboards import DelRouteCallback
from tests.bot_harness import ADMIN, GROUP, OTHER, Harness


@pytest.fixture
def h(repos):
    return Harness(repos)


async def _actions(repos, chat_id=GROUP.id):
    return [(e["action"], e["details"]) for e in reversed(await repos.audit.recent_for_chat(chat_id, limit=50))]


async def test_config_changes_are_audited(h, repos):
    await h.command("/add_route backend prod")
    await h.command("/add_route backend prod")  # duplicate: not audited
    await h.command("/filter backend level=error")
    await h.command("/mute 2h")
    await h.command("/unmute")
    await h.command("/digest all 30")
    await h.command("/tz Asia/Tashkent")
    await h.command("/quiet 22:00-08:00")
    await h.command('/import [{"project": "web"}]')
    [route] = [r for r in await repos.routes.list_for_chat(GROUP.id) if r["project"] == "web"]
    await h.callback(DelRouteCallback(route_id=route["id"]).pack())

    assert await _actions(repos) == [
        ("route.add", "backend / prod"),
        ("filter", "backend level=error"),
        ("mute", "all for 2h"),
        ("unmute", "all"),
        ("digest", "all 30m"),
        ("settings.tz", "Asia/Tashkent"),
        ("settings.quiet", "22:00-08:00"),
        ("routes.import", "1 route(s): 1 added, 0 updated"),
        ("route.remove", "web / *"),
    ]
    entries = await repos.audit.recent_for_chat(GROUP.id)
    assert {e["user_id"] for e in entries} == {ADMIN.id}


async def test_denied_and_noop_commands_are_not_audited(h, repos):
    await h.command("/add_route backend", user=OTHER)
    await h.command("/mute 1h")  # no routes → nothing changed
    await h.command("/filter all clear")
    assert await _actions(repos) == []


async def test_routes_verbose_shows_details_and_history(h, repos):
    await h.command("/routes verbose")
    assert "none" in h.session.last_text

    await h.command("/add_route <i>x</i>")  # rejected, never stored
    await h.command("/add_route backend prod")
    await h.command("/filter backend level=error actions=created")
    await h.command("/digest backend 15")
    await h.command("/routes verbose", user=OTHER)  # read-only, public
    text = h.session.last_text
    assert "<b>backend</b> / prod" in text
    assert "level≥error" in text and "actions=created" in text and "digest 15m" in text
    assert f"by <code>{ADMIN.id}</code>" in text
    assert "Recent changes" in text and "route.add: backend / prod" in text


async def test_audit_details_are_escaped(h, repos):
    await repos.audit.record(GROUP.id, 7, "route.add", "<b>evil</b>")
    await h.command("/routes verbose")
    assert "&lt;b&gt;evil&lt;/b&gt;" in h.session.last_text


async def test_whoami(h):
    await h.command("/whoami")
    assert f"<code>{ADMIN.id}</code>" in h.session.last_text
    assert "Admin: yes" in h.session.last_text
    assert f"<code>{GROUP.id}</code>" in h.session.last_text

    sneaky = User(id=42, is_bot=False, first_name="<b>x</b>", username="o")
    await h.command("/whoami", user=sneaky, chat=Chat(id=42, type="private"))
    assert "Admin: no" in h.session.last_text
    assert "&lt;b&gt;x&lt;/b&gt; (@o)" in h.session.last_text
