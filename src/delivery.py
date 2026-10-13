from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import ReplyParameters

from .burst import BurstCollapser, Summary
from .chat_settings import quiet_until
from .config import settings
from .db import Repositories
from .filters import event_level, skip_reason
from .sentry.formatters import (
    append_footer,
    format_burst_summary,
    format_digest,
    format_event,
    status_footer,
)
from .sentry.parser import ParsedEvent

log = logging.getLogger(__name__)

_MAX_ATTEMPTS = 5
_BACKOFF_BASE_S = 1.0
_BACKOFF_MAX_S = 30.0
_FLUSH_TICK_S = 15.0

# Levels that are delivered even during a chat's quiet hours.
QUIET_HOURS_BYPASS_LEVELS = frozenset({"fatal"})

TargetKey = tuple[int, Optional[int]]  # (chat_id, thread_id)


class Target:
    """Resolution result for one (chat, topic): deliver now, park, or skip."""

    __slots__ = ("chat_id", "thread_id", "skip", "digest_route_id", "route_id")

    def __init__(
        self,
        chat_id: int,
        thread_id: Optional[int] = None,
        skip: Optional[str] = None,
        digest_route_id: Optional[int] = None,
        route_id: Optional[int] = None,
    ) -> None:
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.skip = skip
        self.digest_route_id = digest_route_id
        self.route_id = route_id

    @property
    def key(self) -> TargetKey:
        return (self.chat_id, self.thread_id)

    @property
    def rank(self) -> int:
        """Instant > digest > skipped."""
        if self.skip:
            return 0
        return 1 if self.digest_route_id else 2


async def _resolve_targets(repos: Repositories, event: ParsedEvent) -> dict[TargetKey, Target]:
    """
    Resolve routing for an event.

    Project candidates, most specific first:
    1. "org/slug" (multi-org), then the plain slug
    2. If only a numeric project id is known: the slug learned earlier for
       that id, else the id itself (so `/add_route 123456` works before any
       issue webhook taught us the slug)
    3. DEFAULT_CHAT_ID fallback

    A (chat, topic) may match through several routes; it is skipped only if
    *every* matching route filters the event out, and delivered instantly if
    any passing route is instant (instant beats digest).
    """
    slugs: list[str] = []
    if event.project_slug:
        slugs.append(event.project_slug)
    if event.project_ref_id is not None:
        learned = await repos.projects.slug_for_ref_id(event.project_ref_id)
        if learned and learned not in slugs:
            slugs.append(learned)
        slugs.append(str(event.project_ref_id))
    candidates: list[str] = []
    for slug in slugs:
        if event.org:
            candidates.append(f"{event.org}/{slug}")
        candidates.append(slug)

    for project in candidates:
        routes = await repos.routes.resolve_routes(project, event.environment)
        if not routes:
            continue
        targets: dict[TargetKey, Target] = {}
        for route in routes:
            reason = skip_reason(event, route)
            candidate = Target(
                chat_id=route["chat_id"],
                thread_id=route.get("thread_id"),
                skip=reason,
                digest_route_id=route["id"] if (reason is None and route.get("digest_minutes")) else None,
                route_id=route["id"],
            )
            current = targets.get(candidate.key)
            if current is None or candidate.rank > current.rank:
                targets[candidate.key] = candidate
        return targets

    if settings.default_chat_id:
        t = Target(chat_id=settings.default_chat_id)
        return {t.key: t}
    return {}


async def _resolve_chats(repos: Repositories, event: ParsedEvent) -> list[int]:
    """Chat ids that would receive the event instantly (filters applied)."""
    out: list[int] = []
    for t in (await _resolve_targets(repos, event)).values():
        if t.skip is None and t.digest_route_id is None and t.chat_id not in out:
            out.append(t.chat_id)
    return out


class SendResult:
    __slots__ = ("message_id", "error")

    def __init__(self, message_id: Optional[int] = None, error: Optional[str] = None) -> None:
        self.message_id = message_id
        self.error = error

    @property
    def ok(self) -> bool:
        return self.message_id is not None


async def _send_to_chat(
    bot: Bot,
    chat_id: int,
    text: str,
    reply_to: Optional[int] = None,
    thread_id: Optional[int] = None,
) -> SendResult:
    """
    Send a message, honouring Telegram rate limits and retrying transient
    failures with exponential backoff. `reply_to` threads the message under an
    earlier post (the original is allowed to be gone); `thread_id` targets a
    forum topic.
    """
    reply = (
        ReplyParameters(message_id=reply_to, allow_sending_without_reply=True) if reply_to else None
    )
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            sent = await bot.send_message(
                chat_id, text, reply_parameters=reply, message_thread_id=thread_id
            )
            return SendResult(message_id=sent.message_id)
        except TelegramRetryAfter as exc:
            wait = min(float(exc.retry_after), 120.0)
            log.warning("Rate limited on chat_id=%s; retrying after %.1f s", chat_id, wait)
            await asyncio.sleep(wait)
        except (TelegramNetworkError, TelegramServerError) as exc:
            if attempt == _MAX_ATTEMPTS:
                log.error("Giving up on chat_id=%s after %d attempts: %s", chat_id, attempt, exc)
                return SendResult(error=f"{type(exc).__name__}: {exc}")
            wait = min(_BACKOFF_BASE_S * 2 ** (attempt - 1), _BACKOFF_MAX_S)
            log.warning(
                "Transient Telegram error for chat_id=%s (attempt %d/%d): %s; retry in %.0fs",
                chat_id, attempt, _MAX_ATTEMPTS, exc, wait,
            )
            await asyncio.sleep(wait)
        except TelegramForbiddenError as exc:
            # Bot was blocked / kicked from the chat — retrying is pointless.
            log.warning("Not allowed to message chat_id=%s (%s); skipping", chat_id, exc)
            return SendResult(error=f"forbidden: {exc}")
        except TelegramBadRequest as exc:
            # Permanent: chat not found, malformed HTML, etc.
            log.error("Telegram rejected message for chat_id=%s: %s", chat_id, exc)
            return SendResult(error=f"bad request: {exc}")
        except Exception as exc:
            log.exception("Unexpected error sending to chat_id=%s", chat_id)
            return SendResult(error=f"{type(exc).__name__}: {exc}")
    return SendResult(error="rate limited: retries exhausted")


async def _record(
    repos: Repositories,
    event: ParsedEvent,
    target: Target,
    result: SendResult,
    text: str,
    status: Optional[str] = None,
) -> None:
    try:
        await repos.deliveries.record(
            chat_id=target.chat_id,
            resource=event.resource,
            action=event.action,
            project=event.project_slug or (str(event.project_ref_id) if event.project_ref_id else None),
            environment=event.environment,
            issue_id=event.issue_id,
            title=event.title,
            status=status or ("sent" if result.ok else "failed"),
            error=result.error,
            tg_message_id=result.message_id,
            text=text if status is None else None,  # sent or failed: keep for edits / retries
            thread_id=target.thread_id,
        )
    except Exception:
        log.exception("Could not record delivery for chat_id=%s", target.chat_id)


async def _stamp_original(
    bot: Bot, repos: Repositories, event: ParsedEvent, chat_id: int, prior: dict
) -> None:
    """
    Append a status footer (e.g. "✅ RESOLVED by Alice") to the message that
    first announced the issue, so the chat shows the issue's current state at
    a glance. Best effort: edits of old/deleted messages simply fail quietly.
    """
    footer = status_footer(event)
    if not footer or not prior.get("text") or not prior.get("tg_message_id"):
        return
    new_text = append_footer(prior["text"], footer)
    if new_text is None:
        return
    try:
        await bot.edit_message_text(new_text, chat_id=chat_id, message_id=prior["tg_message_id"])
        await repos.deliveries.update_text(prior["id"], new_text)
    except TelegramRetryAfter:
        log.debug("Rate limited while stamping message %s; skipping", prior["tg_message_id"])
    except Exception as exc:  # noqa: BLE001 — purely cosmetic, never fail delivery
        log.debug("Could not stamp original message %s: %s", prior["tg_message_id"], exc)


async def _park_for_digest(
    repos: Repositories,
    event: ParsedEvent,
    target: Target,
    route_id: int,
    not_before: Optional[datetime] = None,
    reason: str = "queued for digest",
) -> None:
    try:
        await repos.digests.add(
            chat_id=target.chat_id,
            route_id=route_id,
            project=event.project_slug or (str(event.project_ref_id) if event.project_ref_id else None),
            environment=event.environment,
            issue_id=event.issue_id,
            resource=event.resource,
            action=event.action,
            level=event_level(event),
            title=event.title,
            web_url=event.web_url,
            not_before=not_before,
            thread_id=target.thread_id,
        )
        await _record(repos, event, target, SendResult(error=reason), "", status="digest")
    except Exception:
        log.exception("Could not park event for digest chat_id=%s", target.chat_id)


async def _quiet_hold_until(repos: Repositories, event: ParsedEvent, chat_id: int) -> Optional[datetime]:
    """When the chat is in quiet hours and the event isn't fatal, return the hold deadline."""
    level = event_level(event)
    if level in QUIET_HOURS_BYPASS_LEVELS:
        return None
    try:
        row = await repos.chat_settings.get(chat_id)
    except Exception:
        log.exception("Chat settings lookup failed for chat_id=%s", chat_id)
        return None
    return quiet_until(row)


async def send_event(
    bot: Bot,
    repos: Repositories,
    event: ParsedEvent,
    collapser: Optional[BurstCollapser] = None,
) -> None:
    """Resolve routing and deliver the formatted event to all matched targets."""
    targets = await _resolve_targets(repos, event)
    if not targets:
        log.warning(
            "No target chats for resource=%s action=%s project=%s env=%s",
            event.resource, event.action, event.project_slug or event.project_ref_id, event.environment,
        )
        return

    text = format_event(event)
    for target in targets.values():
        chat_id = target.chat_id
        if target.skip is not None:
            log.info("Skipping chat_id=%s for %s.%s: %s", chat_id, event.resource, event.action, target.skip)
            await _record(repos, event, target, SendResult(error=target.skip), text, status="skipped")
            continue

        hold_until = await _quiet_hold_until(repos, event, chat_id)
        if hold_until is not None and target.route_id is not None:
            await _park_for_digest(
                repos, event, target, target.route_id, not_before=hold_until,
                reason=f"quiet hours until {hold_until:%Y-%m-%d %H:%M} UTC",
            )
            continue

        if target.digest_route_id is not None:
            await _park_for_digest(repos, event, target, target.digest_route_id)
            continue

        if collapser is not None and not collapser.check(event, chat_id):
            await _record(
                repos, event, target, SendResult(error="collapsed into burst summary"), text, status="skipped"
            )
            continue

        prior: Optional[dict] = None
        if event.issue_id:
            try:
                prior = await repos.deliveries.last_for_issue(chat_id, event.issue_id)
            except Exception:
                log.exception("Thread lookup failed for chat_id=%s", chat_id)
        result = await _send_to_chat(
            bot, chat_id, text,
            reply_to=prior["tg_message_id"] if prior else None,
            thread_id=target.thread_id,
        )
        await _record(repos, event, target, result, text)
        if prior and result.ok:
            await _stamp_original(bot, repos, event, chat_id, prior)


async def retry_failed(
    bot: Bot, repos: Repositories, chat_id: Optional[int] = None, limit: int = 10
) -> tuple[int, int]:
    """
    Re-send the last `limit` failed deliveries (one chat, or all chats) using
    their stored text. Each original row becomes `retried` so it is never
    re-sent twice; the attempt is logged as a fresh sent/failed row (which can
    itself be retried later). Returns (sent, failed).
    """
    sent = failed = 0
    for row in await repos.deliveries.retryable(chat_id, limit):
        result = await _send_to_chat(bot, row["chat_id"], row["text"], thread_id=row["thread_id"])
        await repos.deliveries.set_status(row["id"], "retried")
        await repos.deliveries.record(
            chat_id=row["chat_id"], resource=row["resource"], action=row["action"],
            project=row["project"], environment=row["environment"], issue_id=row["issue_id"],
            title=row["title"], status="sent" if result.ok else "failed",
            error=result.error, tg_message_id=result.message_id, text=row["text"],
            thread_id=row["thread_id"],
        )
        if result.ok:
            sent += 1
        else:
            failed += 1
    return sent, failed


async def flush_digests(bot: Bot, repos: Repositories, force: bool = False) -> int:
    """Send digests for chats whose period (or quiet-hours hold) has elapsed. Returns chats flushed."""
    now = datetime.now(timezone.utc) + (timedelta(days=3650) if force else timedelta())
    sent = 0
    for chat_id in await repos.digests.due_chats(now):
        items = await repos.digests.pop_for_chat(chat_id, now)
        if not items:
            continue
        # One digest per forum topic within the chat.
        by_thread: dict[Optional[int], list[dict]] = {}
        for it in items:
            by_thread.setdefault(it.get("thread_id"), []).append(it)
        for thread_id, group in by_thread.items():
            text = format_digest(group)
            target = Target(chat_id=chat_id, thread_id=thread_id)
            result = await _send_to_chat(bot, chat_id, text, thread_id=thread_id)
            sample = ParsedEvent(
                resource="digest", action="sent", project_slug=None, project_ref_id=None,
                environment=None, title=f"{len(group)} events", web_url=None,
            )
            await _record(repos, sample, target, result, text)
        sent += 1
    return sent


async def send_burst_summary(bot: Bot, repos: Repositories, summary: Summary) -> None:
    """Post the '+N more events' line, threaded under the issue's last message."""
    text = format_burst_summary(summary.sample, summary.count, summary.window_s)
    prior = None
    try:
        prior = await repos.deliveries.last_for_issue(summary.chat_id, summary.issue_id)
    except Exception:
        log.exception("Thread lookup failed for burst summary")
    thread_id = prior.get("thread_id") if prior else None
    result = await _send_to_chat(
        bot, summary.chat_id, text,
        reply_to=prior["tg_message_id"] if prior else None, thread_id=thread_id,
    )
    await _record(repos, summary.sample, Target(summary.chat_id, thread_id), result, text)


async def delivery_worker(
    queue: "asyncio.Queue[Optional[ParsedEvent]]",
    bot: Bot,
    repos: Repositories,
    collapser: Optional[BurstCollapser] = None,
) -> None:
    """
    Background asyncio task that consumes ParsedEvent items and delivers them.
    Putting None into the queue triggers a clean shutdown. Between items it
    periodically flushes burst summaries and due digests.
    """
    if collapser is None:
        collapser = BurstCollapser(settings.burst_window_seconds)
    log.info("Delivery worker started (burst window %ss)", collapser.window_s)
    while True:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=_FLUSH_TICK_S)
        except asyncio.TimeoutError:
            await _flush_bursts(bot, repos, collapser)
            await _safe_flush_digests(bot, repos)
            continue
        if item is None:
            log.info("Delivery worker: shutdown sentinel received")
            queue.task_done()
            break
        try:
            await send_event(bot, repos, item, collapser)
        except Exception:
            log.exception("Unhandled error in delivery worker")
        finally:
            queue.task_done()
        await _flush_bursts(bot, repos, collapser)
        await _safe_flush_digests(bot, repos)
    # Final flush so pending summaries are not lost on shutdown. Digest items
    # persist in the DB, so they survive restarts and are NOT force-flushed.
    await _flush_bursts(bot, repos, collapser, force=True)
    log.info("Delivery worker stopped")


async def _flush_bursts(
    bot: Bot, repos: Repositories, collapser: BurstCollapser, force: bool = False
) -> None:
    if not collapser.enabled:
        return
    now = time.monotonic() + collapser.window_s if force else None
    for summary in collapser.flush_due(now):
        try:
            await send_burst_summary(bot, repos, summary)
        except Exception:
            log.exception("Failed to send burst summary for chat_id=%s", summary.chat_id)


async def _safe_flush_digests(bot: Bot, repos: Repositories) -> None:
    try:
        await flush_digests(bot, repos)
    except Exception:
        log.exception("Digest flush failed")
