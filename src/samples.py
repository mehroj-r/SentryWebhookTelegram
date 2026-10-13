"""
Sample events for /test — run through the real formatter so a chat can see
what alerts will look like (and that the bot can post there) before Sentry
sends anything.
"""
from __future__ import annotations

from typing import Optional

from .sentry.parser import ParsedEvent

KINDS: tuple[str, ...] = ("issue", "error", "event_alert", "metric_alert", "release")
_URL = "https://sentry.io/organizations/example/issues/1234567/"


def sample_event(kind: str, project: Optional[str] = None, environment: Optional[str] = None) -> Optional[ParsedEvent]:
    """A realistic ParsedEvent of `kind`, or None for an unknown kind."""
    project = project or "example-project"
    env = environment or "production"
    frame = {"filename": "app/services/payments.py", "function": "charge_card", "lineno": 87}
    context = {
        "release": "backend@2.14.0", "top_frame": frame, "transaction": "POST /api/checkout",
        "request_method": "POST", "request_url": "https://shop.example.com/api/checkout",
        "user": "id:4821", "runtime": "CPython 3.12.4", "os": "Linux",
        "tags": {"region": "eu-west-1", "customer_tier": "pro"},
        "breadcrumbs": [
            {"category": "http", "message": "POST https://payments.example.com/charge [502]"},
            {"category": "query", "message": "SELECT * FROM orders WHERE id = %s"},
        ],
    }
    title = "ConnectionError: payment gateway timed out"
    if kind == "issue":
        return ParsedEvent(
            resource="issue", action="created", project_slug=project, project_ref_id=None,
            environment=None, title=title, web_url=_URL, issue_id="1234567",
            extra={
                "short_id": f"{project.upper()}-42", "level": "error", "status": "unresolved",
                "culprit": "app.services.payments in charge_card", "count": 1, "user_count": 1,
            },
        )
    if kind == "error":
        return ParsedEvent(
            resource="error", action="created", project_slug=project, project_ref_id=None,
            environment=env, title=title, web_url=_URL, issue_id="1234567",
            extra={**context, "level": "error", "event_id": "9f2c1e0a7b3d4c5e8f6a1b2c3d4e5f60"},
        )
    if kind == "event_alert":
        return ParsedEvent(
            resource="event_alert", action="triggered", project_slug=project, project_ref_id=None,
            environment=env, title=title, web_url=_URL, issue_id="1234567",
            extra={**context, "level": "error", "triggered_rule": "Payment errors in production"},
        )
    if kind == "metric_alert":
        return ParsedEvent(
            resource="metric_alert", action="critical", project_slug=project, project_ref_id=None,
            environment=env, title="Checkout p95 latency > 2s", web_url=_URL,
            extra={"description_text": "p95(transaction.duration) was 2840ms in the last 5 minutes"},
        )
    if kind == "release":
        return ParsedEvent(
            resource="release", action="deployed", project_slug=project, project_ref_id=None,
            environment=env, title="backend@2.14.0", web_url=None,
            extra={
                "version": "backend@2.14.0", "projects": [project], "deploy_name": "deploy #318",
                "commit_count": 12, "authors": ["alice", "bob"],
            },
        )
    return None
