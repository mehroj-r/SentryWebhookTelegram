from src.sentry.formatters import format_event
from src.sentry.parser import parse


def test_release_payload_routes_by_project_and_env():
    payload = {"action": "deployed", "data": {
        "release": {"version": "backend@1.4.2", "url": "https://sentry.io/r/1", "projects": ["backend", "worker"],
                    "commit_count": 12, "authors": [{"name": "Jane"}, {"email": "bob@x.io"}]},
        "deploy": {"environment": "production", "name": "prod-eu"},
    }}
    ev = parse(payload, "deploy")
    assert ev.resource == "release" and ev.project_slug == "backend" and ev.environment == "production"
    assert ev.title == "backend@1.4.2 deployed to production"
    text = format_event(ev)
    assert text.startswith("🚀 <b>Release DEPLOYED</b>: <a href=\"https://sentry.io/r/1\">backend@1.4.2</a>")
    assert "<code>backend</code>, <code>worker</code>" in text
    assert "production (prod-eu)" in text and "Commits: 12" in text and "Jane, bob@x.io" in text


def test_release_minimal_payload():
    ev = parse({"action": "", "data": {"version": "1.0", "project": "api"}}, "release")
    assert ev.project_slug == "api" and ev.action == "deployed"
    assert "1.0" in format_event(ev)
