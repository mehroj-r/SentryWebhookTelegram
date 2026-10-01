from __future__ import annotations

import html
from typing import Optional

from .parser import ParsedEvent

# Telegram hard limit for a text message.
TELEGRAM_MAX_LEN = 4096
_TITLE_LIMIT = 300

# ── emoji maps ─────────────────────────────────────────────────────────────────

_LEVEL_EMOJI: dict[str, str] = {
    "fatal": "💀",
    "critical": "🔴",
    "error": "🔴",
    "warning": "🟡",
    "info": "🔵",
    "debug": "⚪",
}

_ACTION_EMOJI: dict[str, str] = {
    "created": "🆕",
    "resolved": "✅",
    "assigned": "👤",
    "archived": "📦",
    "ignored": "📦",
    "unresolved": "🔓",
    "triggered": "⚡",
    "critical": "🔴",
    "warning": "🟡",
    "deleted": "🗑️",
    "updated": "✏️",
}

# ── helpers ────────────────────────────────────────────────────────────────────


def _e(value: object) -> str:
    """HTML-escape a value to safe string."""
    return html.escape(str(value)) if value is not None else ""


def _truncate(text: str, limit: int = 300) -> str:
    return text[:limit] + ("…" if len(text) > limit else "")


def _safe_url(url: Optional[str]) -> Optional[str]:
    """Telegram rejects messages whose <a href> isn't an http(s)/tg URL."""
    if not url:
        return None
    url = url.strip()
    if url.startswith(("http://", "https://", "tg://")):
        return url
    return None


def _link(text: str, url: Optional[str], limit: int = _TITLE_LIMIT) -> str:
    """Wrap (truncated) text in an HTML link if url is usable."""
    text = _truncate(text, limit)
    url = _safe_url(url)
    if url:
        return f'<a href="{_e(url)}">{_e(text)}</a>'
    return _e(text)


def _issue_emoji(event: ParsedEvent) -> str:
    """
    For a *new* issue the severity level is the most useful signal; for any
    other lifecycle action (resolved, assigned, ...) the action is.
    """
    if event.action in ("created", "", None):
        level = str(event.extra.get("level") or "")
        if level in _LEVEL_EMOJI:
            return _LEVEL_EMOJI[level]
    return _ACTION_EMOJI.get(event.action, "🔔")


def _by_actor(event: ParsedEvent) -> str:
    return f" by {_e(event.actor)}" if event.actor else ""


def _clamp(text: str) -> str:
    """
    Last-resort guard so we never exceed Telegram's limit. Field-level
    truncation keeps us well below it in practice; if we still overflow, cut
    whole lines (never mid-tag) so the HTML stays well-formed.
    """
    if len(text) <= TELEGRAM_MAX_LEN:
        return text
    lines = text.split("\n")
    out: list[str] = []
    total = 0
    for line in lines:
        if total + len(line) + 1 > TELEGRAM_MAX_LEN - 2:
            break
        out.append(line)
        total += len(line) + 1
    if not out:  # a single gigantic first line: strip tags and cut hard
        plain = html.escape(html.unescape(text.replace("<", " <")))
        return plain[: TELEGRAM_MAX_LEN - 1] + "…"
    out.append("…")
    return "\n".join(out)


# ── public API ─────────────────────────────────────────────────────────────────


def format_event(event: ParsedEvent) -> str:
    """Return an HTML-formatted Telegram message for a ParsedEvent."""
    fn = _FORMATTERS.get(event.resource, _format_generic)
    return _clamp(fn(event))


# ── per-resource formatters ────────────────────────────────────────────────────


def _format_issue(event: ParsedEvent) -> str:
    ex = event.extra
    emoji = _issue_emoji(event)
    action_label = _e(event.action.upper() or "EVENT")
    title_part = _link(event.title, event.web_url)

    lines: list[str] = [f"{emoji} <b>Issue {action_label}</b>{_by_actor(event)}: {title_part}"]

    if ex.get("short_id"):
        lines.append(f"🆔 <code>{_e(ex['short_id'])}</code>")
    if ex.get("project_name"):
        lines.append(f"📁 Project: {_e(ex['project_name'])}")
    if ex.get("culprit"):
        lines.append(f"📍 <i>{_e(_truncate(str(ex['culprit']), 120))}</i>")
    if ex.get("level"):
        level_emoji = _LEVEL_EMOJI.get(str(ex["level"]), "")
        lines.append(f"{level_emoji} Level: <b>{_e(ex['level'])}</b>".strip())
    if ex.get("status"):
        status_str = _e(ex["status"])
        if ex.get("substatus"):
            status_str += f" ({_e(ex['substatus'])})"
        lines.append(f"Status: {status_str}")
    if ex.get("assigned_to"):
        lines.append(f"👤 Assigned: {_e(_truncate(str(ex['assigned_to']), 100))}")
    if ex.get("count") is not None or ex.get("user_count") is not None:
        count = ex.get("count")
        users = ex.get("user_count")
        lines.append(
            f"📊 Events: {_e(count if count is not None else '?')} | "
            f"Users: {_e(users if users is not None else '?')}"
        )

    return "\n".join(lines)


def _format_event_alert(event: ParsedEvent) -> str:
    emoji = _ACTION_EMOJI.get(event.action, "⚡")
    title_part = _link(event.title, event.web_url)
    lines: list[str] = [f"{emoji} <b>Event Alert</b>: {title_part}"]

    if rule := event.extra.get("triggered_rule"):
        lines.append(f"📋 Rule: <i>{_e(_truncate(str(rule), 120))}</i>")
    if culprit := event.extra.get("culprit"):
        lines.append(f"📍 <i>{_e(_truncate(str(culprit), 120))}</i>")
    if env := event.environment:
        lines.append(f"🌍 Env: <code>{_e(env)}</code>")
    if level := event.extra.get("level"):
        level_emoji = _LEVEL_EMOJI.get(str(level), "")
        lines.append(f"{level_emoji} Level: <b>{_e(level)}</b>".strip())

    return "\n".join(lines)


def _format_metric_alert(event: ParsedEvent) -> str:
    emoji = _ACTION_EMOJI.get(event.action, "📊")
    title_part = _link(event.title, event.web_url)
    lines: list[str] = [f"{emoji} <b>Metric Alert</b>: {title_part}"]

    if event.project_slug:
        lines.append(f"📁 Project: <code>{_e(event.project_slug)}</code>")
    if env := event.environment:
        lines.append(f"🌍 Env: <code>{_e(env)}</code>")
    if desc := event.extra.get("description_text"):
        lines.append(f"<code>{_e(_truncate(str(desc), 400))}</code>")

    return "\n".join(lines)


def _format_error(event: ParsedEvent) -> str:
    level = event.extra.get("level") or "error"
    emoji = _LEVEL_EMOJI.get(str(level), "🔴")
    title_part = _link(event.title, event.web_url)
    lines: list[str] = [f"{emoji} <b>Error</b>: {title_part}"]

    if msg := event.extra.get("message"):
        lines.append(f"<i>{_e(_truncate(str(msg), 200))}</i>")
    if culprit := event.extra.get("culprit"):
        lines.append(f"📍 <i>{_e(_truncate(str(culprit), 120))}</i>")
    if env := event.environment:
        lines.append(f"🌍 Env: <code>{_e(env)}</code>")
    if plat := event.extra.get("platform"):
        lines.append(f"🖥️ Platform: {_e(plat)}")
    if eid := event.extra.get("event_id"):
        lines.append(f"🆔 ID: <code>{_e(eid)}</code>")

    return "\n".join(lines)


def _format_comment(event: ParsedEvent) -> str:
    emoji = _ACTION_EMOJI.get(event.action, "💬")
    lines: list[str] = [f"{emoji} <b>Comment {_e(event.action.upper())}</b>{_by_actor(event)}"]

    if iid := event.extra.get("issue_id"):
        lines.append(f"🔗 Issue: #{_e(iid)}")
    if project := event.project_slug:
        lines.append(f"📁 Project: <code>{_e(project)}</code>")
    if text := event.extra.get("comment"):
        snippet = _truncate(str(text), 300)
        lines.append(f"<blockquote>{_e(snippet)}</blockquote>")

    return "\n".join(lines)


def _format_installation(event: ParsedEvent) -> str:
    emoji = "🔌" if event.action == "created" else "🔌❌"
    lines: list[str] = [f"{emoji} <b>Integration {_e(event.action.upper())}</b>"]

    if app := event.extra.get("app_slug"):
        lines.append(f"App: <code>{_e(app)}</code>")
    if org := event.extra.get("org_slug"):
        lines.append(f"Org: <code>{_e(org)}</code>")
    if status := event.extra.get("status"):
        lines.append(f"Status: {_e(status)}")

    return "\n".join(lines)


def _format_generic(event: ParsedEvent) -> str:
    emoji = _ACTION_EMOJI.get(event.action, "🔔")
    lines: list[str] = [
        f"{emoji} <b>{_e(event.resource.upper())}</b>: {_e(event.action)}",
        f"<i>{_e(_truncate(event.title, _TITLE_LIMIT))}</i>",
    ]
    if raw := event.extra.get("raw_data"):
        lines.append(f"<code>{_e(_truncate(str(raw), 400))}</code>")

    return "\n".join(lines)


_FORMATTERS = {
    "issue": _format_issue,
    "event_alert": _format_event_alert,
    "metric_alert": _format_metric_alert,
    "error": _format_error,
    "comment": _format_comment,
    "installation": _format_installation,
}
