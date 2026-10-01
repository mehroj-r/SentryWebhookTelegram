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


# Issue lifecycle actions that should be stamped onto the original message.
STATUS_ACTIONS = frozenset({"resolved", "unresolved", "archived", "ignored", "assigned"})


def status_footer(event: ParsedEvent) -> Optional[str]:
    """One-line status stamp for the original message, or None if not applicable."""
    if event.resource != "issue" or event.action not in STATUS_ACTIONS:
        return None
    emoji = _ACTION_EMOJI.get(event.action, "🔔")
    parts = [f"{emoji} <b>{_e(event.action.upper())}</b>"]
    if event.action == "assigned" and event.extra.get("assigned_to"):
        parts.append(f"to {_e(_truncate(str(event.extra['assigned_to']), 60))}")
    if event.actor:
        parts.append(f"by {_e(event.actor)}")
    return " ".join(parts)


def append_footer(original_html: str, footer: str) -> Optional[str]:
    """Original message plus a footer line; None if it would exceed Telegram's limit."""
    combined = f"{original_html}\n{footer}"
    return combined if len(combined) <= TELEGRAM_MAX_LEN else None


def format_burst_summary(sample: ParsedEvent, count: int, window_s: float) -> str:
    """One line for N suppressed repeats of the same issue."""
    minutes = max(1, round(window_s / 60))
    title_part = _link(sample.title, sample.web_url, limit=150)
    where = ""
    if sample.environment:
        where = f" (<code>{_e(sample.environment)}</code>)"
    return (
        f"🔁 <b>+{count} more</b> event{'s' if count != 1 else ''} for {title_part}{where} "
        f"in the last {minutes} min"
    )


def format_digest(items: list[dict], max_groups: int = 25) -> str:
    """
    One message summarising parked events, grouped by issue (or title when
    there is no issue id), most frequent first.
    """
    groups: dict[tuple, dict] = {}
    for it in items:
        key = (it.get("project"), it.get("issue_id") or it.get("title"))
        g = groups.setdefault(key, {"count": 0, "item": it, "actions": set()})
        g["count"] += 1
        g["actions"].add(it.get("action") or "")
        # keep the most recent representative
        g["item"] = it
    ordered = sorted(groups.values(), key=lambda g: -g["count"])

    total = len(items)
    header = f"📰 <b>Digest</b>: {total} event{'s' if total != 1 else ''} across {len(groups)} issue{'s' if len(groups) != 1 else ''}"
    lines = [header]
    for g in ordered[:max_groups]:
        it = g["item"]
        level_emoji = _LEVEL_EMOJI.get(str(it.get("level") or ""), "•")
        where = _e(it.get("project") or "?")
        if it.get("environment"):
            where += f"/{_e(it['environment'])}"
        actions = ",".join(sorted(a for a in g["actions"] if a))
        suffix = f" <i>{_e(actions)}</i>" if actions and actions != "created" else ""
        lines.append(
            f"{level_emoji} ×{g['count']} <code>{where}</code> {_link(it.get('title') or '(no title)', it.get('web_url'), limit=120)}{suffix}"
        )
    if len(ordered) > max_groups:
        lines.append(f"… and {len(ordered) - max_groups} more issues")
    return _clamp("\n".join(lines))


# ── public API ─────────────────────────────────────────────────────────────────


def format_event(event: ParsedEvent) -> str:
    """Return an HTML-formatted Telegram message for a ParsedEvent."""
    fn = _FORMATTERS.get(event.resource, _format_generic)
    return _clamp(fn(event))


def _context_lines(ex: dict) -> list[str]:
    """Compact context for event bodies: release, where, who, platform."""
    lines: list[str] = []
    if ex.get("release"):
        rel = _truncate(str(ex["release"]), 60)
        if ex.get("dist"):
            rel += f" ({_truncate(str(ex['dist']), 20)})"
        lines.append(f"📦 Release: <code>{_e(rel)}</code>")
    frame = ex.get("top_frame")
    if frame and (frame.get("filename") or frame.get("function")):
        loc = _truncate(str(frame.get("filename") or "?"), 80)
        if frame.get("lineno"):
            loc += f":{frame['lineno']}"
        fn = f" in <code>{_e(_truncate(str(frame['function']), 60))}</code>" if frame.get("function") else ""
        lines.append(f"📍 <code>{_e(loc)}</code>{fn}")
    elif ex.get("culprit"):
        lines.append(f"📍 <i>{_e(_truncate(str(ex['culprit']), 120))}</i>")
    if ex.get("transaction") and ex.get("transaction") != ex.get("culprit"):
        lines.append(f"🧭 <code>{_e(_truncate(str(ex['transaction']), 100))}</code>")
    if ex.get("request_url"):
        method = f"{_e(ex['request_method'])} " if ex.get("request_method") else ""
        lines.append(f"🌐 {method}{_link(str(ex['request_url']), str(ex['request_url']), limit=100)}")
    if ex.get("user"):
        lines.append(f"👤 User: {_e(_truncate(str(ex['user']), 60))}")
    platform_bits = [str(ex[k]) for k in ("browser", "os", "runtime") if ex.get(k)]
    if platform_bits:
        lines.append(f"🖥️ {_e(' · '.join(platform_bits))}")
    elif ex.get("platform"):
        lines.append(f"🖥️ Platform: {_e(ex['platform'])}")
    return lines


def _details_block(ex: dict) -> Optional[str]:
    """Expandable blockquote with tags and the last breadcrumbs (collapsed by default)."""
    rows: list[str] = []
    tags = ex.get("tags") or {}
    if tags:
        rows.append("🏷 " + ", ".join(f"{_e(k)}={_e(_truncate(str(v), 40))}" for k, v in tags.items()))
    crumbs = ex.get("breadcrumbs") or []
    for c in crumbs:
        cat = f"[{_e(c['category'])}] " if c.get("category") else ""
        rows.append(f"🍞 {cat}{_e(_truncate(str(c.get('message') or ''), 100))}")
    if not rows:
        return None
    return "<blockquote expandable>" + "\n".join(rows) + "</blockquote>"


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
    if ex.get("is_regression"):
        lines.append("↩️ <b>Regression</b>")
    if ex.get("exc_value") and str(ex["exc_value"]) not in event.title:
        lines.append(f"<i>{_e(_truncate(str(ex['exc_value']), 200))}</i>")
    if ex.get("filename") or ex.get("function"):
        loc = _truncate(str(ex.get("filename") or "?"), 80)
        fn = f" in <code>{_e(_truncate(str(ex['function']), 60))}</code>" if ex.get("function") else ""
        lines.append(f"📍 <code>{_e(loc)}</code>{fn}")
    elif ex.get("culprit"):
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
    if msg := event.extra.get("message"):
        if msg != event.title:
            lines.append(f"<i>{_e(_truncate(str(msg), 200))}</i>")
    if env := event.environment:
        lines.append(f"🌍 Env: <code>{_e(env)}</code>")
    if level := event.extra.get("level"):
        level_emoji = _LEVEL_EMOJI.get(str(level), "")
        lines.append(f"{level_emoji} Level: <b>{_e(level)}</b>".strip())
    lines.extend(_context_lines(event.extra))
    if details := _details_block(event.extra):
        lines.append(details)

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
        if msg != event.title:
            lines.append(f"<i>{_e(_truncate(str(msg), 200))}</i>")
    frame = event.extra.get("top_frame") or {}
    if frame.get("exc_value") and frame.get("exc_value") != event.title:
        lines.append(f"<i>{_e(_truncate(str(frame['exc_value']), 200))}</i>")
    if env := event.environment:
        lines.append(f"🌍 Env: <code>{_e(env)}</code>")
    lines.extend(_context_lines(event.extra))
    if eid := event.extra.get("event_id"):
        lines.append(f"🆔 ID: <code>{_e(eid)}</code>")
    if details := _details_block(event.extra):
        lines.append(details)

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
