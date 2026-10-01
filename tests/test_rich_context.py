import json

from src.sentry.formatters import format_event
from src.sentry.parser import parse

ERROR_PAYLOAD = {
    "action": "created",
    "data": {
        "error": {
            "event_id": "abc123",
            "title": "ZeroDivisionError: division by zero",
            "message": "",
            "level": "error",
            "platform": "python",
            "project": 7,
            "release": "backend@1.4.2",
            "dist": "7",
            "environment": "production",
            "transaction": "/api/orders/",
            "culprit": "orders.views in create",
            "issue_url": "https://sentry.io/api/0/organizations/acme/issues/555/",
            "web_url": "https://sentry.io/organizations/acme/issues/555/events/abc123/",
            "user": {"id": "u1", "email": "jane@example.com", "ip_address": "1.2.3.4"},
            "request": {"url": "https://shop.example.com/api/orders/", "method": "POST"},
            "tags": [["browser", "Chrome 120"], ["os", "Linux"], ["server_name", "web-3"], ["level", "error"],
                     ["environment", "production"], ["custom", "x"]],
            "contexts": {"browser": {"name": "Chrome", "version": "120.0"}, "os": {"name": "Linux"},
                         "runtime": {"name": "CPython", "version": "3.12.1"}},
            "sdk": {"name": "sentry.python.django"},
            "exception": {"values": [{
                "type": "ZeroDivisionError", "value": "division by zero",
                "stacktrace": {"frames": [
                    {"filename": "django/core/handlers/base.py", "function": "inner", "lineno": 10, "in_app": False},
                    {"filename": "orders/views.py", "function": "create", "lineno": 42, "in_app": True},
                    {"filename": "orders/math.py", "function": "ratio", "lineno": 7, "in_app": True},
                    {"filename": "decimal.py", "function": "__truediv__", "lineno": 1, "in_app": False},
                ]},
            }]},
            "breadcrumbs": {"values": [
                {"category": "query", "message": "SELECT 1"},
                {"category": "http", "data": {"url": "https://pay.example.com/charge"}},
                {"category": "log", "message": "<charging> & finalising"},
            ]},
        }
    },
}


def test_error_context_parsed():
    ev = parse(json.loads(json.dumps(ERROR_PAYLOAD)), "error")
    ex = ev.extra
    assert ex["release"] == "backend@1.4.2" and ex["dist"] == "7"
    assert ex["top_frame"]["filename"] == "orders/math.py" and ex["top_frame"]["lineno"] == 7
    assert ex["user"] == "jane@example.com"
    assert ex["browser"] == "Chrome 120.0" and ex["runtime"] == "CPython 3.12.1"
    assert ex["request_url"].endswith("/orders/") and ex["request_method"] == "POST"
    assert ex["tags"] == {"browser": "Chrome 120", "os": "Linux", "server_name": "web-3"}
    assert [c["category"] for c in ex["breadcrumbs"]] == ["query", "http", "log"]
    assert ex["breadcrumbs"][1]["message"] == "https://pay.example.com/charge"


def test_error_message_renders_context_and_escapes():
    text = format_event(parse(ERROR_PAYLOAD, "error"))
    assert "📦 Release: <code>backend@1.4.2 (7)</code>" in text
    assert "orders/math.py:7</code> in <code>ratio</code>" in text
    assert "👤 User: jane@example.com" in text
    assert "🌐 POST <a href=" in text
    assert "Chrome 120.0 · Linux · CPython 3.12.1" in text
    assert "<blockquote expandable>" in text and "&lt;charging&gt; &amp; finalising" in text
    assert "🆔 ID: <code>abc123</code>" in text


def test_issue_metadata_rendered():
    payload = {"action": "created", "data": {"issue": {
        "title": "TypeError", "level": "error", "substatus": "regressed",
        "metadata": {"type": "TypeError", "value": "x is not a function", "filename": "app.js", "function": "boot"},
    }}}
    text = format_event(parse(payload, "issue"))
    assert "↩️ <b>Regression</b>" in text
    assert "x is not a function" in text
    assert "<code>app.js</code> in <code>boot</code>" in text


def test_missing_context_is_fine():
    text = format_event(parse({"action": "created", "data": {"error": {"title": "Bare"}}}, "error"))
    assert text.startswith("🔴 <b>Error</b>: Bare")
    assert "blockquote" not in text
