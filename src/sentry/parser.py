from __future__ import annotations

import re
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
    issue_id: Optional[str] = None  # Sentry issue id, used to thread follow-up messages
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


_ISSUE_URL_RE = re.compile(r"/issues/(\d+)/?")


def _issue_id_from(*candidates: Any) -> Optional[str]:
    """First usable issue id: a direct id, or one embedded in an issue URL."""
    for value in candidates:
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, int):
            return str(value)
        text = str(value).strip()
        if text.isdigit():
            return text
        match = _ISSUE_URL_RE.search(text)
        if match:
            return match.group(1)
    return None


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


_IGNORED_TAGS = {"environment", "level", "release", "transaction", "url", "user", "sentry:user",
                 "sentry:release", "sentry:dist", "handled", "mechanism", "logger"}
_PREFERRED_TAGS = ("browser", "browser.name", "os", "os.name", "device", "server_name",
                   "runtime", "runtime.name", "client_os.name")


def _tags_dict(tags: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(tags, list):
        return out
    for tag in tags:
        if isinstance(tag, (list, tuple)) and len(tag) == 2 and tag[0]:
            out[str(tag[0])] = str(tag[1])
        elif isinstance(tag, dict) and tag.get("key"):
            out[str(tag["key"])] = str(tag.get("value", ""))
    return out


def _top_frame(exception: Any) -> Optional[dict[str, Any]]:
    """Innermost in-app frame of the last exception value (fallback: any frame)."""
    exc = _dict(exception)
    values = exc.get("values")
    if not isinstance(values, list) or not values:
        return None
    last = _dict(values[-1])
    frames = _dict(last.get("stacktrace")).get("frames")
    if not isinstance(frames, list) or not frames:
        return None
    frame_dicts = [f for f in frames if isinstance(f, dict)]
    if not frame_dicts:
        return None
    in_app = [f for f in frame_dicts if f.get("in_app") or f.get("inApp")]
    frame = (in_app or frame_dicts)[-1]  # Sentry orders frames outermost → innermost
    return {
        "filename": frame.get("filename") or frame.get("abs_path") or frame.get("absPath"),
        "function": frame.get("function"),
        "lineno": frame.get("lineno") or frame.get("lineNo"),
        "exc_type": last.get("type"),
        "exc_value": last.get("value"),
    }


def _breadcrumbs(breadcrumbs: Any, limit: int = 3) -> list[dict[str, Any]]:
    bc = _dict(breadcrumbs)
    values = bc.get("values") if bc else breadcrumbs
    if not isinstance(values, list):
        return []
    out = []
    for crumb in values[-limit:]:
        if not isinstance(crumb, dict):
            continue
        msg = crumb.get("message") or _dict(crumb.get("data")).get("url") or ""
        out.append({"category": crumb.get("category"), "message": str(msg)[:120], "level": crumb.get("level")})
    return out


def _user_display(user: Any) -> Optional[str]:
    u = _dict(user)
    if not u:
        return None
    return _str_or_none(u.get("email") or u.get("username") or u.get("id") or u.get("ip_address"))


def _event_context(obj: dict) -> dict[str, Any]:
    """Shared rich fields for `error` and `event_alert` event bodies."""
    tags = _tags_dict(obj.get("tags"))
    contexts = _dict(obj.get("contexts"))
    browser = _dict(contexts.get("browser"))
    os_ctx = _dict(contexts.get("os"))
    runtime = _dict(contexts.get("runtime"))

    shown_tags: dict[str, str] = {}
    for key in _PREFERRED_TAGS:
        if key in tags and len(shown_tags) < 4:
            shown_tags[key] = tags[key]
    if not shown_tags:
        for key, value in tags.items():
            if key not in _IGNORED_TAGS and len(shown_tags) < 3:
                shown_tags[key] = value

    request = _dict(obj.get("request"))
    return {
        "release": _str_or_none(obj.get("release") or tags.get("release") or tags.get("sentry:release")),
        "dist": _str_or_none(obj.get("dist")),
        "transaction": _str_or_none(obj.get("transaction") or tags.get("transaction")),
        "request_url": _str_or_none(request.get("url") or tags.get("url")),
        "request_method": _str_or_none(request.get("method")),
        "user": _user_display(obj.get("user")),
        "browser": _str_or_none(
            " ".join(x for x in (browser.get("name"), browser.get("version")) if x) or tags.get("browser")
        ),
        "os": _str_or_none(" ".join(x for x in (os_ctx.get("name"), os_ctx.get("version")) if x) or tags.get("os")),
        "runtime": _str_or_none(" ".join(x for x in (runtime.get("name"), runtime.get("version")) if x)),
        "tags": shown_tags,
        "top_frame": _top_frame(obj.get("exception")),
        "breadcrumbs": _breadcrumbs(obj.get("breadcrumbs")),
        "sdk": _str_or_none(_dict(obj.get("sdk")).get("name")),
    }


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
        "release": _parse_release,
        "deploy": _parse_release,
    }
    fn = parsers.get(resource, _parse_generic)
    event = fn(action, data, resource)
    event.actor = actor
    return event


# ── per-resource parsers ────────────────────────────────────────────────────────


def _parse_issue(action: str, data: dict, _resource: str = "issue") -> ParsedEvent:
    issue = _dict(data.get("issue"))
    project = _dict(issue.get("project"))
    metadata = _dict(issue.get("metadata"))
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
        issue_id=_issue_id_from(issue.get("id")),
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
            "platform": issue.get("platform"),
            "exc_type": _str_or_none(metadata.get("type")),
            "exc_value": _str_or_none(metadata.get("value")),
            "filename": _str_or_none(metadata.get("filename")),
            "function": _str_or_none(metadata.get("function")),
            "is_regression": bool(_dict(issue.get("statusDetails")).get("inRelease")) or issue.get("substatus") == "regressed",
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
        issue_id=_issue_id_from(event.get("issue_id"), event.get("issue_url"), event.get("web_url")),
        extra={
            "triggered_rule": data.get("triggered_rule"),
            "platform": event.get("platform"),
            "level": event.get("level") or _tag_value(event.get("tags"), "level"),
            "culprit": event.get("culprit"),
            "issue_url": event.get("issue_url"),
            "message": event.get("message"),
            **_event_context(event),
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
        issue_id=_issue_id_from(error.get("issue_id"), error.get("issue_url"), error.get("web_url")),
        extra={
            "event_id": error.get("event_id"),
            "message": error.get("message"),
            "level": error.get("level") or _tag_value(error.get("tags"), "level"),
            "platform": error.get("platform"),
            "culprit": error.get("culprit"),
            "issue_url": error.get("issue_url"),
            **_event_context(error),
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
        issue_id=_issue_id_from(issue_id),
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


def _parse_release(action: str, data: dict, resource: str = "release") -> ParsedEvent:
    """
    Release / deploy notification.

    Accepted shape (also what a CI job can POST to the Sentry endpoint, signed
    with the same client secret):

        {"action": "deployed", "data": {
            "release": {"version": "backend@1.4.2", "url": "...", "projects": ["backend"],
                        "commit_count": 12, "authors": [{"name": "Jane"}]},
            "deploy":  {"environment": "production", "name": "prod-eu", "url": "..."}}}
    """
    release = _dict(data.get("release"))
    deploy = _dict(data.get("deploy"))

    projects = release.get("projects") or data.get("projects")
    project_slug: Optional[str] = None
    if isinstance(projects, list) and projects:
        first = projects[0]
        project_slug = _str_or_none(first.get("slug") if isinstance(first, dict) else first)
    project_slug = project_slug or _str_or_none(data.get("project") or data.get("project_slug"))

    version = _str_or_none(release.get("version") or release.get("shortVersion") or data.get("version"))
    environment = _str_or_none(deploy.get("environment") or release.get("environment") or data.get("environment"))

    authors = release.get("authors")
    author_names: list[str] = []
    if isinstance(authors, list):
        for a in authors:
            name = _str_or_none(a.get("name") or a.get("email")) if isinstance(a, dict) else _str_or_none(a)
            if name:
                author_names.append(name)

    verb = action or "deployed"
    title = f"{version or '(unknown version)'} {verb}"
    if environment:
        title += f" to {environment}"

    return ParsedEvent(
        resource="release",
        action=verb,
        project_slug=project_slug,
        project_ref_id=None,
        environment=environment,
        title=title,
        web_url=_str_or_none(deploy.get("url") or release.get("url") or data.get("web_url")),
        extra={
            "version": version,
            "deploy_name": _str_or_none(deploy.get("name")),
            "commit_count": release.get("commitCount") or release.get("commit_count"),
            "authors": author_names[:5],
            "projects": [p.get("slug") if isinstance(p, dict) else str(p) for p in projects]
            if isinstance(projects, list) else None,
            "date_released": _str_or_none(release.get("dateReleased") or release.get("date_released")),
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
