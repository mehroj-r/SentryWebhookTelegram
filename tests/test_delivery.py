from src.delivery import _resolve_chats
from src.sentry.parser import ParsedEvent


def _ev(**kw):
    base = dict(resource="error", action="created", project_slug=None, project_ref_id=None,
                environment=None, title="t", web_url=None)
    base.update(kw)
    return ParsedEvent(**base)


async def test_resolve_by_learned_slug(repos):
    await repos.projects.upsert("backend", ref_id=42)
    await repos.routes.add("backend", None, 10)
    assert await _resolve_chats(repos, _ev(project_ref_id=42)) == [10]


async def test_resolve_by_numeric_id_route(repos):
    await repos.routes.add("42", None, 11)
    assert await _resolve_chats(repos, _ev(project_ref_id=42)) == [11]


async def test_resolve_falls_back_to_default(repos, monkeypatch):
    from src import delivery
    monkeypatch.setattr(delivery.settings, "default_chat_id", 999)
    assert await _resolve_chats(repos, _ev(project_slug="nope")) == [999]
