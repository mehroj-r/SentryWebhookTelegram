"""
Burst collapsing: Sentry's `error` and `event_alert` hooks fire once per
*event*, so a hot issue can produce hundreds of near-identical webhooks in a
few minutes. We post the first one, swallow repeats for the same
(chat, issue) inside a window, and then post a single summary.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterator, Optional

from .sentry.parser import ParsedEvent

# Resources that are emitted per event (not per issue lifecycle change).
BURSTY_RESOURCES = frozenset({"error", "event_alert"})


@dataclass
class _State:
    last_sent: float
    suppressed: int = 0
    first_suppressed: float = 0.0
    sample: Optional[ParsedEvent] = None
    stale_hits: int = field(default=0, repr=False)


@dataclass
class Summary:
    chat_id: int
    issue_id: str
    count: int
    window_s: float
    sample: ParsedEvent


class BurstCollapser:
    """
    Decide per (chat, issue) whether an event is posted now or folded into a
    later summary. Not thread-safe; it lives in the single delivery worker.
    """

    def __init__(self, window_s: float, max_keys: int = 10_000) -> None:
        self.window_s = window_s
        self._max_keys = max_keys
        self._states: dict[tuple[int, str], _State] = {}

    @property
    def enabled(self) -> bool:
        return self.window_s > 0

    @staticmethod
    def applies(event: ParsedEvent) -> bool:
        return event.resource in BURSTY_RESOURCES and bool(event.issue_id)

    def check(self, event: ParsedEvent, chat_id: int, now: Optional[float] = None) -> bool:
        """
        True → send this event now. False → suppressed (counted for the summary).
        """
        if not self.enabled or not self.applies(event):
            return True
        now = time.monotonic() if now is None else now
        key = (chat_id, event.issue_id or "")
        state = self._states.get(key)
        if state is None:
            self._evict_if_needed(now)
            self._states[key] = _State(last_sent=now)
            return True
        if now - state.last_sent < self.window_s:
            if state.suppressed == 0:
                state.first_suppressed = now
            state.suppressed += 1
            state.sample = event
            return False
        # Window elapsed. Any suppressed count is reported by flush_due(); send this one.
        state.last_sent = now
        return True

    def flush_due(self, now: Optional[float] = None) -> Iterator[Summary]:
        """Yield summaries for keys whose window has elapsed with suppressed events."""
        now = time.monotonic() if now is None else now
        for key, state in list(self._states.items()):
            if state.suppressed and now - state.last_sent >= self.window_s:
                assert state.sample is not None
                yield Summary(
                    chat_id=key[0],
                    issue_id=key[1],
                    count=state.suppressed,
                    window_s=now - state.first_suppressed,
                    sample=state.sample,
                )
                state.suppressed = 0
                state.sample = None
                state.last_sent = now  # the summary itself counts as a post
            elif not state.suppressed and now - state.last_sent >= 2 * self.window_s:
                del self._states[key]  # idle key; forget it

    def _evict_if_needed(self, now: float) -> None:
        if len(self._states) < self._max_keys:
            return
        # Drop the oldest idle keys first.
        for key, state in sorted(self._states.items(), key=lambda kv: kv[1].last_sent):
            if state.suppressed:
                continue
            del self._states[key]
            if len(self._states) < self._max_keys * 0.9:
                break
