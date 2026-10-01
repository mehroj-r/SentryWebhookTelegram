from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ParsedEvent:
    resource: str                   # sentry-hook-resource value
    action: str                     # e.g. "created", "triggered", "critical"
    project_slug: Optional[str]     # resolved project slug (may be None)
    project_ref_id: Optional[int]   # numeric project id when only id is available
    environment: Optional[str]      # environment name if present in payload
    title: str                      # human-readable summary
    web_url: Optional[str]          # link to view in Sentry UI
    actor: Optional[str] = None     # who performed the action (resolved/assigned/...)
    extra: dict[str, Any] = field(default_factory=dict)  # additional display fields


# ── helpers ────────────────────────────────────────────────────────────────────


def _dict(value: Any) -> dict:
    """Return `value` if it is a dict, else an empty dict (payload fields may be null)."""
    return value if isinstance(value, dict) else {}


def _str_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _split_project_ref(raw: Any) -> tuple[Optional[str], Optional[int]]:
    """
    Sentry sends `project` either as a numeric id (int or numeric string)
    or, in some payloads, as a slug. Return (slug, ref_id).
    """
    if raw is None or isinstance(raw, bool):
        return None, None
    if isinstance(raw, int):
        return None, raw
    if isinstance(raw, dict):
        return _str_or_none(raw.get("slug")), _int_or_none(raw.get("id"))
    text = str(raw).strip()
    if not text:
        return None, None
    try:
        return None, int(text)
    except ValueError:
        return text, None


def _actor_display(actor: Any) -> Optional[str]:
    actor = _dict(actor)
    if not actor:
        return None
    if actor.get("type") == "application":
        return None  # Sentry itself; not interesting to show
    return _str_or_none(actor.get("name") or actor.get("email") or actor.get("id"))


def _tag_value(tags: Any, key: str) -> Optional[str]:
    """Sentry event tags come as a list of [key, value] pairs (or dicts)."""
    if not isinstance(tags, list):
        return None
    for tag in tags:
        if isinstance(tag, (list, tuple)) and len(tag) == 2 and tag[0] == key:
            return _str_or_none(tag[1])
        if isinstance(tag, dict) and tag.get("key") == key:
            return _str_or_none(tag.get("value"))
    return None


# ── public API ─────────────────────────────────────────────────────────────────


def parse(payload: dict[str, Any], resource: str) -> ParsedEvent:
    """Dispatch to a resource-specific parser and return a ParsedEvent."""
    action = _str_or_none(payload.get("action")) or ""
    data = _dict(payload.get("data"))
    actor = _actor_display(payload.get("actor"))

    parsers = {
        "issue": _parse_issue,
        "event_alert": _parse_event_alert,
        "metric_alert": _parse_metric_alert,
        "error": _parse_error,
        "comment": _parse_comment,
        "installation": _parse_installation,
    }
    fn = parsers.get(resource, _parse_generic)
    event = fn(action, data, resource)
    event.actor = actor
    return event


# ── per-resource parsers ────────────────────────────────────────────────────────


def _parse_issue(action: str, data: dict, _resource: str = "issue") -> ParsedEvent:
    issue = _dict(data.get("issue"))
    project = _dict(issue.get("project"))
    project_slug = _str_or_none(project.get("slug"))
    project_ref_id = _int_or_none(project.get("id"))

    assigned_to = issue.get("assignedTo")
    if isinstance(assigned_to, dict):
        assigned_display = (
            assigned_to.get("name") or assigned_to.get("email") or str(assigned_to)
        )
    elif assigned_to:
        assigned_display = str(assigned_to)
    else:
        assigned_display = None

    return ParsedEvent(
        resource="issue",
        action=action,
        project_slug=project_slug,
        project_ref_id=project_ref_id,
        environment=None,  # issue webhooks don't carry environment
        title=_str_or_none(issue.get("title")) or "(no title)",
        web_url=_str_or_none(issue.get("web_url") or issue.get("permalink")),
        extra={
            "short_id": issue.get("shortId"),
            "status": issue.get("status"),
            "substatus": issue.get("substatus"),
            "level": issue.get("level"),
            "culprit": issue.get("culprit"),
            "assigned_to": assigned_display,
            "count": issue.get("count"),
            "user_count": issue.get("userCount"),
            "first_seen": issue.get("firstSeen"),
            "last_seen": issue.get("lastSeen"),
            "project_name": _str_or_none(project.get("name")),
        },
    )


def _parse_event_alert(action: str, data: dict, _resource: str = "event_alert") -> ParsedEvent:
    event = _dict(data.get("event"))
    project_slug, project_ref_id = _split_project_ref(event.get("project"))
    environment = _str_or_none(event.get("environment")) or _tag_value(
        event.get("tags"), "environment"
    )

    return ParsedEvent(
        resource="event_alert",
        action=action,
        project_slug=project_slug,
        project_ref_id=project_ref_id,
        environment=environment,
        title=_str_or_none(event.get("title") or data.get("triggered_rule")) or "(event alert)",
        web_url=_str_or_none(event.get("web_url") or event.get("url")),
        extra={
            "triggered_rule": data.get("triggered_rule"),
            "platform": event.get("platform"),
            "level": event.get("level") or _tag_value(event.get("tags"), "level"),
            "culprit": event.get("culprit"),
            "issue_url": event.get("issue_url"),
        },
    )


def _parse_metric_alert(action: str, data: dict, _resource: str = "metric_alert") -> ParsedEvent:
    metric_alert = _dict(data.get("metric_alert"))
    alert_rule = _dict(metric_alert.get("alert_rule"))

    # Metric alerts list their project slugs on the incident and on the rule.
    projects = metric_alert.get("projects") or alert_rule.get("projects")
    project_slug: Optional[str] = None
    if isinstance(projects, list) and projects:
        project_slug = _str_or_none(projects[0])

    return ParsedEvent(
        resource="metric_alert",
        action=action,
        project_slug=project_slug,
        project_ref_id=None,
        environment=_str_or_none(alert_rule.get("environment")),
        title=_str_or_none(data.get("description_title") or alert_rule.get("name"))
        or "(metric alert)",
        web_url=_str_or_none(data.get("web_url")),
        extra={
            "description_text": data.get("description_text"),
            "alert_rule_name": alert_rule.get("name"),
            "status": metric_alert.get("status"),
            "projects": projects if isinstance(projects, list) else None,
        },
    )


def _parse_error(action: str, data: dict, _resource: str = "error") -> ParsedEvent:
    error = _dict(data.get("error"))
    project_slug, project_ref_id = _split_project_ref(error.get("project"))
    environment = _str_or_none(error.get("environment")) or _tag_value(
        error.get("tags"), "environment"
    )

    return ParsedEvent(
        resource="error",
        action=action,
        project_slug=project_slug,
        project_ref_id=project_ref_id,
        environment=environment,
        title=_str_or_none(error.get("title")) or "(error)",
        web_url=_str_or_none(error.get("web_url") or error.get("url")),
        extra={
            "event_id": error.get("event_id"),
            "message": error.get("message"),
            "level": error.get("level") or _tag_value(error.get("tags"), "level"),
            "platform": error.get("platform"),
            "culprit": error.get("culprit"),
            "issue_url": error.get("issue_url"),
        },
    )


def _parse_comment(action: str, data: dict, _resource: str = "comment") -> ParsedEvent:
    issue_id = data.get("issue_id")
    return ParsedEvent(
        resource="comment",
        action=action,
        project_slug=_str_or_none(data.get("project_slug")),
        project_ref_id=None,
        environment=None,
        title=f"Comment on issue #{issue_id}" if issue_id else "Comment",
        web_url=None,
        extra={
            "comment": data.get("comment"),
            "comment_id": data.get("comment_id"),
            "issue_id": issue_id,
            "timestamp": data.get("timestamp"),
        },
    )


def _parse_installation(action: str, data: dict, _resource: str = "installation") -> ParsedEvent:
    installation = _dict(data.get("installation"))
    app = _dict(installation.get("app"))
    org = _dict(installation.get("organization"))
    app_slug = _str_or_none(app.get("slug")) or ""
    org_slug = _str_or_none(org.get("slug")) or ""
    return ParsedEvent(
        resource="installation",
        action=action,
        project_slug=None,
        project_ref_id=None,
        environment=None,
        title=f"Integration {action}: {app_slug} @ {org_slug}",
        web_url=None,
        extra={
            "uuid": installation.get("uuid"),
            "status": installation.get("status"),
            "app_slug": app_slug,
            "org_slug": org_slug,
            "code": installation.get("code"),
        },
    )


def _parse_generic(action: str, data: dict, resource: str = "") -> ParsedEvent:
    return ParsedEvent(
        resource=resource or "unknown",
        action=action,
        project_slug=None,
        project_ref_id=None,
        environment=None,
        title=f"{resource or 'unknown'}: {action or '-'}",
        web_url=None,
        extra={"raw_data": str(data)[:500]},
    )
