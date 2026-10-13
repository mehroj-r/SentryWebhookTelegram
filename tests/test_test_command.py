import pytest

from src.samples import KINDS, sample_event
from src.sentry.formatters import format_event
from tests.bot_harness import GROUP, OTHER, Harness


@pytest.fixture
def h(repos):
    return Harness(repos)


@pytest.mark.parametrize("kind", KINDS)
def test_every_sample_formats(kind):
    event = sample_event(kind, "backend", "staging")
    assert event.resource == kind and event.project_slug == "backend"
    assert format_event(event)


def test_unknown_kind():
    assert sample_event("nope") is None


async def test_default_issue_without_routes(h):
    await h.command("/test")
    sample, note = h.session.sent[-2:]
    assert "Issue CREATED" in sample.text and "EXAMPLE-PROJECT-42" in sample.text
    assert "no routes yet" in note.text


async def test_uses_chat_route_and_reports_filters(h, repos):
    await h.command("/add_route acme/backend prod")
    await h.command("/test error")
    sample, note = h.session.sent[-2:]
    assert sample.text.startswith("<code>[acme]</code>") and "<code>prod</code>" in sample.text
    assert "would deliver" in note.text

    await h.command("/filter all level=fatal")
    await h.command("/test error")
    assert "would skip it: level 'error' below 'fatal'" in h.session.last_text


async def test_wildcard_routes_must_actually_match(h, repos):
    await h.command("/add_route backend")
    await h.command("/add_route web-*")
    await h.command("/filter web-* level=debug")
    await h.command("/filter backend actions=resolved")
    await h.command("/test")  # sample project 'backend' — web-* must not count
    assert "would skip it" in h.session.last_text


async def test_usage_and_admin_only(h):
    await h.command("/test bogus")
    assert "Usage" in h.session.last_text
    await h.command("/test", user=OTHER)
    assert "not allowed" in h.session.last_text
    assert all("Issue CREATED" not in m.text for m in h.session.sent)
