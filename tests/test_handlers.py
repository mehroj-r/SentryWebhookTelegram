import pytest

from src.bot.keyboards import ANY_ENV, DelRouteCallback, EnvCallback, ProjectCallback, key_for
from tests.bot_harness import ADMIN, GROUP, OTHER, Harness


@pytest.fixture
def h(repos):
    return Harness(repos)


async def test_add_route_rejects_html_and_adds_valid(h, repos):
    await h.command("/add_route <b>x</b>")
    assert "Invalid" in h.session.last_text
    await h.command("/add_route backend production")
    assert "Route added" in h.session.last_text
    assert len(await repos.routes.list_for_chat(GROUP.id)) == 1


async def test_non_admin_is_denied(h, repos):
    await h.command("/add_route backend", user=OTHER)
    assert "not allowed" in h.session.last_text
    assert await repos.routes.list_for_chat(GROUP.id) == []


async def test_subscribe_flow_with_long_names(h, repos):
    slug = "a-very-long-project-slug-that-goes-on-and-on-forever"
    env = "an-equally-long-environment-name-for-testing-purposes"
    await repos.projects.upsert(slug, 5, "Long")
    await repos.environments.register(slug, env)
    await h.command("/subscribe")
    kb = h.session.sent[-1].reply_markup
    data = kb.inline_keyboard[0][0].callback_data
    assert len(data.encode()) <= 64
    await h.callback(data)
    await h.callback(EnvCallback(project_key=key_for(slug), env_key=key_for(env)).pack())
    assert "Route added" in h.session.edits[-1].text
    [route] = await repos.routes.list_for_chat(GROUP.id)
    assert route["project"] == slug and route["environment"] == env


async def test_unknown_project_key_alerts(h):
    await h.callback(ProjectCallback(key="deadbeefdead").pack())
    assert h.session.answers[-1].show_alert is True


async def test_routes_delete_scoped_to_chat(h, repos):
    await repos.routes.add("p", None, 999)  # another chat's route
    [foreign] = await repos.routes.list_for_chat(999)
    await h.callback(DelRouteCallback(route_id=foreign["id"]).pack())
    assert len(await repos.routes.list_for_chat(999)) == 1
    assert "already gone" in h.session.answers[-1].text


async def test_filter_mute_unmute(h, repos):
    await h.command("/add_route backend")
    await h.command("/filter backend level=error actions=created,resolved")
    [r] = await repos.routes.list_for_chat(GROUP.id)
    assert r["min_level"] == "error" and r["actions"] == "created,resolved"

    await h.command("/filter backend level=bogus")
    assert "Unknown level" in h.session.last_text

    await h.command("/mute 2h")
    [r] = await repos.routes.list_for_chat(GROUP.id)
    assert r["muted_until"] is not None
    await h.command("/routes")
    assert "🔇" in h.session.sent[-1].reply_markup.inline_keyboard[0][0].text

    await h.command("/unmute")
    [r] = await repos.routes.list_for_chat(GROUP.id)
    assert r["muted_until"] is None

    await h.command("/filter all clear")
    [r] = await repos.routes.list_for_chat(GROUP.id)
    assert r["min_level"] is None and r["actions"] is None


async def test_last_and_chat_id(h, repos):
    await h.command("/last")
    assert "Nothing" in h.session.last_text
    await h.command("/chat_id")
    assert str(GROUP.id) in h.session.last_text
