"""
Minimal Prometheus metrics (text exposition format 0.0.4) without a client
library: a few process-wide labelled counters plus gauges computed at scrape
time.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

PREFIX = "sentry_telegram"


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels(names: tuple[str, ...], values: tuple[str, ...]) -> str:
    if not names:
        return ""
    return "{" + ",".join(f'{n}="{_escape_label(v)}"' for n, v in zip(names, values)) + "}"


class Counter:
    def __init__(self, name: str, help_text: str, labels: tuple[str, ...] = ()) -> None:
        self.name = f"{PREFIX}_{name}_total"
        self.help = help_text
        self.label_names = labels
        self._values: dict[tuple[str, ...], float] = {}
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = tuple(str(labels.get(n, "")) for n in self.label_names)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def value(self, **labels: str) -> float:
        return self._values.get(tuple(str(labels.get(n, "")) for n in self.label_names), 0.0)

    def reset(self) -> None:
        with self._lock:
            self._values.clear()

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        with self._lock:
            items = sorted(self._values.items())
        if not items and not self.label_names:
            items = [((), 0.0)]
        lines += [f"{self.name}{_labels(self.label_names, k)} {v:g}" for k, v in items]
        return lines


_START = time.time()

webhooks_received = Counter("webhooks_received", "Sentry webhooks accepted and queued, by resource.", ("resource",))
webhooks_rejected = Counter(
    "webhooks_rejected", "Sentry webhooks rejected, by reason (signature, stale, json, busy).", ("reason",)
)
webhooks_deduplicated = Counter("webhooks_deduplicated", "Sentry webhooks dropped as duplicate Request-IDs.")
deliveries = Counter(
    "deliveries", "Delivery outcomes per target chat (sent, failed, skipped, digest).", ("status",)
)

COUNTERS: tuple[Counter, ...] = (webhooks_received, webhooks_rejected, webhooks_deduplicated, deliveries)


def reset() -> None:
    for c in COUNTERS:
        c.reset()


def render(queue_size: Optional[Callable[[], int]] = None) -> str:
    lines: list[str] = []
    for c in COUNTERS:
        lines += c.render()
    if queue_size is not None:
        lines += [
            f"# HELP {PREFIX}_queue_size Events waiting for delivery to Telegram.",
            f"# TYPE {PREFIX}_queue_size gauge",
            f"{PREFIX}_queue_size {queue_size()}",
        ]
    lines += [
        f"# HELP {PREFIX}_start_time_seconds Unix time the process started.",
        f"# TYPE {PREFIX}_start_time_seconds gauge",
        f"{PREFIX}_start_time_seconds {_START:.3f}",
    ]
    return "\n".join(lines) + "\n"
