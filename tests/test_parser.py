from src.sentry.parser import parse


def test_issue_with_null_fields_does_not_crash():
    ev = parse({"action": "created", "data": {"issue": None}}, "issue")
    assert ev.resource == "issue"
    assert ev.title == "(no title)"


def test_payload_with_null_data():
    ev = parse({"action": "x", "data": None}, "error")
    assert ev.resource == "error"


def test_issue_project_and_actor():
    payload = {
        "action": "resolved",
        "actor": {"type": "user", "name": "Alice"},
        "data": {
            "issue": {
                "title": "ZeroDivisionError",
                "project": {"id": "42", "slug": "backend", "name": "Backend"},
                "level": "error",
                "shortId": "BACKEND-1",
            }
        },
    }
    ev = parse(payload, "issue")
    assert ev.project_slug == "backend"
    assert ev.project_ref_id == 42
    assert ev.actor == "Alice"
    assert ev.extra["project_name"] == "Backend"


def test_metric_alert_extracts_project_and_environment():
    payload = {
        "action": "critical",
        "data": {
            "description_title": "Critical: Too many errors",
            "metric_alert": {
                "projects": ["backend"],
                "alert_rule": {"name": "Too many errors", "environment": "production"},
            },
            "web_url": "https://sentry.io/x",
        },
    }
    ev = parse(payload, "metric_alert")
    assert ev.project_slug == "backend"
    assert ev.environment == "production"


def test_error_environment_from_tags():
    payload = {
        "action": "created",
        "data": {
            "error": {
                "title": "Boom",
                "project": 7,
                "tags": [["environment", "staging"], ["level", "warning"]],
            }
        },
    }
    ev = parse(payload, "error")
    assert ev.project_ref_id == 7
    assert ev.project_slug is None
    assert ev.environment == "staging"
    assert ev.extra["level"] == "warning"


def test_event_alert_project_slug_string():
    ev = parse({"action": "triggered", "data": {"event": {"project": "my-proj"}}}, "event_alert")
    assert ev.project_slug == "my-proj"
    assert ev.project_ref_id is None


def test_unknown_resource_generic():
    ev = parse({"action": "foo", "data": {"x": 1}}, "something_new")
    assert ev.resource == "something_new"
