from src.sentry.formatters import TELEGRAM_MAX_LEN, format_event
from src.sentry.parser import ParsedEvent, parse


def _issue(**overrides):
    base = dict(
        resource="issue", action="created", project_slug="p", project_ref_id=1,
        environment=None, title="T", web_url=None,
    )
    base.update(overrides)
    return ParsedEvent(**base)


def test_html_is_escaped():
    text = format_event(_issue(title="<script>alert(1)</script> & co"))
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


def test_unsafe_url_not_linked():
    text = format_event(_issue(web_url="javascript:alert(1)"))
    assert "<a href" not in text


def test_safe_url_linked():
    text = format_event(_issue(web_url="https://sentry.io/issues/1"))
    assert '<a href="https://sentry.io/issues/1">' in text


def test_long_title_clamped_under_limit():
    text = format_event(_issue(title="x" * 10_000, extra={"culprit": "y" * 10_000}))
    assert len(text) <= TELEGRAM_MAX_LEN


def test_resolved_uses_action_emoji_not_level():
    text = format_event(_issue(action="resolved", extra={"level": "error"}))
    assert text.startswith("✅")


def test_actor_rendered():
    ev = parse(
        {"action": "assigned", "actor": {"type": "user", "name": "Bob <x>"},
         "data": {"issue": {"title": "t"}}},
        "issue",
    )
    text = format_event(ev)
    assert "by Bob &lt;x&gt;" in text
