from src.delivery import _resolve_chats
from src.sentry.parser import ParsedEvent
from tests.bot_harness import GROUP, Harness


def _ev(slug, env=None):
    return ParsedEvent(resource="issue", action="created", project_slug=slug, project_ref_id=None,
                       environment=env, title="t", web_url=None)


async def test_exact_beats_pattern_beats_catch_all(repos):
    await repos.routes.add("*", None, 1)
    await repos.routes.add("backend-*", None, 2)
    await repos.routes.add("backend-api", None, 3)
    assert await _resolve_chats(repos, _ev("backend-api")) == [3]
    assert await _resolve_chats(repos, _ev("backend-worker")) == [2, 1] or \
           sorted(await _resolve_chats(repos, _ev("backend-worker"))) == [1, 2]
    assert await _resolve_chats(repos, _ev("frontend")) == [1]


async def test_pattern_with_environment_fallback(repos):
    await repos.routes.add("*-prod", "production", 5)
    await repos.routes.add("*-prod", None, 6)
    assert await _resolve_chats(repos, _ev("shop-prod", "production")) == [5]
    assert await _resolve_chats(repos, _ev("shop-prod", "staging")) == [6]
    assert await _resolve_chats(repos, _ev("shop-dev", "production")) == []


async def test_add_wildcard_route_via_command(repos):
    h = Harness(repos)
    await h.command("/add_route backend-* production")
    assert "Route added" in h.session.last_text
    [r] = await repos.routes.list_for_chat(GROUP.id)
    assert r["project"] == "backend-*"
