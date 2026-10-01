"""
Per-route noise control: minimum level, action allowlist, temporary mute.

Pure functions so they are trivially testable; the delivery worker applies
them to every (event, route) pair.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from .sentry.parser import ParsedEvent

LEVELS: tuple[str, ...] = ("debug", "info", "warning", "error", "fatal")
_LEVEL_RANK = {name: i for i, name in enumerate(LEVELS)}
_LEVEL_ALIASES = {"critical": "fatal", "warn": "warning", "err": "error"}

# Metric alerts carry no level; map their action to one so level filters apply.
_METRIC_ACTION_LEVEL = {"critical": "error", "warning": "warning", "resolved": "info"}

_DURATION_RE = re.compile(r"^(\d+)\s*([smhd])$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def normalize_level(value: str) -> Optional[str]:
    v = value.strip().lower()
    v = _LEVEL_ALIASES.get(v, v)
    return v if v in _LEVEL_RANK else None


def event_level(event: ParsedEvent) -> Optional[str]:
    raw = event.extra.get("level")
    if raw:
        return normalize_level(str(raw))
    if event.resource == "metric_alert":
        return _METRIC_ACTION_LEVEL.get(event.action)
    return None


def parse_duration(text: str) -> Optional[timedelta]:
    """'30m', '2h', '1d' → timedelta; None if malformed."""
    m = _DURATION_RE.match(text.strip().lower())
    if not m:
        return None
    return timedelta(seconds=int(m.group(1)) * _UNIT_SECONDS[m.group(2)])


def parse_actions(text: str) -> Optional[list[str]]:
    actions = [a.strip().lower() for a in text.split(",") if a.strip()]
    return actions or None


def skip_reason(event: ParsedEvent, route: dict, now: Optional[datetime] = None) -> Optional[str]:
    """
    Return why this event must NOT be delivered via `route`, or None to deliver.

    `route` keys: min_level, actions (comma-separated), muted_until.
    """
    now = now or datetime.now(timezone.utc)

    muted_until = route.get("muted_until")
    if muted_until is not None:
        if muted_until.tzinfo is None:  # SQLite returns naive UTC
            muted_until = muted_until.replace(tzinfo=timezone.utc)
        if muted_until > now:
            return f"muted until {muted_until:%Y-%m-%d %H:%M} UTC"

    allowed = route.get("actions")
    if allowed:
        allowed_set = {a.strip() for a in allowed.split(",") if a.strip()}
        if event.action not in allowed_set:
            return f"action '{event.action}' not in [{allowed}]"

    min_level = route.get("min_level")
    if min_level:
        level = event_level(event)
        # Events that have no level (comments, installs) pass through.
        if level is not None and _LEVEL_RANK[level] < _LEVEL_RANK.get(min_level, 0):
            return f"level '{level}' below '{min_level}'"

    return None


def describe_filters(route: dict) -> str:
    """Short suffix for route labels, e.g. ' [≥error] [created,resolved] 🔇'."""
    parts: list[str] = []
    if route.get("min_level"):
        parts.append(f"[≥{route['min_level']}]")
    if route.get("actions"):
        parts.append(f"[{route['actions']}]")
    muted_until = route.get("muted_until")
    if muted_until is not None:
        if muted_until.tzinfo is None:
            muted_until = muted_until.replace(tzinfo=timezone.utc)
        if muted_until > datetime.now(timezone.utc):
            parts.append("🔇")
    return (" " + " ".join(parts)) if parts else ""
