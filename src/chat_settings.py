"""Per-chat preferences: timezone and quiet hours (pure helpers)."""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_HHMM_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
DEFAULT_TZ = "UTC"


def parse_timezone(name: str) -> Optional[str]:
    """Validate an IANA zone name; return its canonical spelling or None."""
    try:
        return ZoneInfo(name.strip()).key
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None


def tz_for(settings_row: Optional[dict]) -> ZoneInfo:
    name = (settings_row or {}).get("timezone") or DEFAULT_TZ
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return ZoneInfo(DEFAULT_TZ)


def parse_hhmm(text: str) -> Optional[time]:
    m = _HHMM_RE.match(text.strip())
    if not m:
        return None
    return time(int(m.group(1)), int(m.group(2)))


def parse_quiet_range(text: str) -> Optional[tuple[str, str]]:
    """'22:00-08:00' → ('22:00', '08:00'); None if malformed."""
    start, sep, end = text.partition("-")
    if not sep:
        return None
    s, e = parse_hhmm(start), parse_hhmm(end)
    if s is None or e is None or s == e:
        return None
    return f"{s.hour:02d}:{s.minute:02d}", f"{e.hour:02d}:{e.minute:02d}"


def quiet_until(settings_row: Optional[dict], now: Optional[datetime] = None) -> Optional[datetime]:
    """
    If the chat is in its quiet hours right now, return the UTC datetime when
    they end; otherwise None. Ranges may wrap midnight (22:00-08:00).
    """
    row = settings_row or {}
    start_s, end_s = row.get("quiet_start"), row.get("quiet_end")
    if not start_s or not end_s:
        return None
    start, end = parse_hhmm(start_s), parse_hhmm(end_s)
    if start is None or end is None:
        return None

    tz = tz_for(row)
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(tz)
    today = local.date()

    start_dt = datetime.combine(today, start, tzinfo=tz)
    end_dt = datetime.combine(today, end, tzinfo=tz)
    if start < end:
        if start_dt <= local < end_dt:
            return end_dt.astimezone(timezone.utc)
        return None
    # wraps midnight
    if local >= start_dt:
        return (end_dt + timedelta(days=1)).astimezone(timezone.utc)
    if local < end_dt:
        return end_dt.astimezone(timezone.utc)
    return None


def format_local(dt: datetime, settings_row: Optional[dict], fmt: str = "%m-%d %H:%M") -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz_for(settings_row)).strftime(fmt)
