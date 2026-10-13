import pytest
from aiogram.types import Chat, User

from src.bot import middlewares
from src.bot.keyboards import DelRouteCallback
from src.config import settings
from tests.bot_harness import ADMIN, GROUP, OTHER, Harness

ANON_BOT = User(id=1087968824, is_bot=True, first_name="Group")


@pytest.fixture
def h(repos, monkeypatch):
    monkeypatch.setattr(settings, "admin_ids", [])
    middlewares.clear_admin_cache()
    yield Harness(repos)
    middlewares.clear_admin_cache()


async def _route_count(repos, chat=GROUP):
    return len(await repos.routes.list_for_chat(chat.id))


async def test_group_admins_and_owner_allowed_members_denied(h, repos):
    h.session.members[(GROUP.id, ADMIN.id)] = "administrator"
    h.session.members[(GROUP.id, 7)] = "creator"
    await h.command("/add_route a")
    await h.command("/add_route b", user=User(id=7, is_bot=False, first_name="Owner"))
    assert await _route_count(repos) == 2

    await h.command("/add_route c", user=OTHER)
    assert "not allowed" in h.session.last_text
    assert await _route_count(repos) == 2


async def test_private_chat_is_open(h, repos):
    dm = Chat(id=OTHER.id, type="private")
    await h.command("/add_route a", user=OTHER, chat=dm)
    assert await _route_count(repos, dm) == 1
    assert not any(type(c).__name__ == "GetChatMember" for c in h.session.calls)


async def test_anonymous_group_admin_allowed(h, repos):
    await h.command("/add_route a", user=ANON_BOT, sender_chat=GROUP)
    assert await _route_count(repos) == 1


async def test_member_status_is_cached(h, repos):
    h.session.members[(GROUP.id, ADMIN.id)] = "administrator"
    await h.command("/add_route a")
    h.session.members[(GROUP.id, ADMIN.id)] = "member"  # demoted, but cache still says admin
    await h.command("/add_route b")
    lookups = [c for c in h.session.calls if type(c).__name__ == "GetChatMember"]
    assert len(lookups) == 1 and await _route_count(repos) == 2

    middlewares.clear_admin_cache()
    await h.command("/add_route c")
    assert "not allowed" in h.session.last_text


async def test_api_error_denies_without_caching(h, repos):
    h.session.members[(GROUP.id, ADMIN.id)] = "error"
    await h.command("/add_route a")
    assert "not allowed" in h.session.last_text
    h.session.members[(GROUP.id, ADMIN.id)] = "administrator"
    await h.command("/add_route a")
    assert await _route_count(repos) == 1


async def test_callbacks_use_message_chat(h, repos):
    await repos.routes.add("p", None, GROUP.id)
    [route] = await repos.routes.list_for_chat(GROUP.id)
    await h.callback(DelRouteCallback(route_id=route["id"]).pack(), user=OTHER)
    assert h.session.answers[-1].show_alert and await _route_count(repos) == 1
    h.session.members[(GROUP.id, OTHER.id)] = "administrator"
    middlewares.clear_admin_cache()  # newly promoted admins otherwise wait out the cache
    await h.callback(DelRouteCallback(route_id=route["id"]).pack(), user=OTHER)
    assert await _route_count(repos) == 0


async def test_whoami_reports_chat_admin(h):
    h.session.members[(GROUP.id, ADMIN.id)] = "creator"
    await h.command("/whoami")
    assert "Admin: yes" in h.session.last_text
    await h.command("/whoami", user=OTHER)
    assert "Admin: no" in h.session.last_text


async def test_admin_ids_override_chat_roles(h, repos, monkeypatch):
    monkeypatch.setattr(settings, "admin_ids", [ADMIN.id])
    h.session.members[(GROUP.id, OTHER.id)] = "creator"
    await h.command("/add_route a", user=OTHER)
    assert "not allowed" in h.session.last_text
    await h.command("/add_route a")
    assert await _route_count(repos) == 1
