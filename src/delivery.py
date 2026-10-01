from __future__ import annotations

import asyncio
import logging
from typing import Optional

from aiogram import Bot
from aiogram.types import ReplyParameters
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)

from .config import settings
from .db import Repositories
from .filters import skip_reason
from .sentry.formatters import append_footer, format_event, status_footer
from .sentry.parser import ParsedEvent

log = logging.getLogger(__name__)

_MAX_ATTEMPTS = 5
_BACKOFF_BASE_S = 1.0
_BACKOFF_MAX_S = 30.0


async def _resolve_targets(repos: Repositories, event: ParsedEvent) -> dict[int, Optional[str]]:
    """
    Map each target chat id to None (deliver) or a skip reason (filtered out).

    A chat may match through several routes; it is skipped only if *every*
    matching route filters the event out.

    Resolution order:
    1. Routes for the project slug (exact env, then "any env" wildcard)
    2. If only a numeric project id is known: routes keyed by the slug we
       learned earlier for that id, else routes keyed by the id itself
       (so `/add_route 123456` works before any issue webhook taught us the slug)
    3. DEFAULT_CHAT_ID fallback
    """
    candidates: list[str] = []
    if event.project_slug:
        candidates.append(event.project_slug)
    if event.project_ref_id is not None:
        learned = await repos.projects.slug_for_ref_id(event.project_ref_id)
        if learned and learned not in candidates:
            candidates.append(learned)
        candidates.append(str(event.project_ref_id))

    for project in candidates:
        routes = await repos.routes.resolve_routes(project, event.environment)
        if routes:
            targets: dict[int, Optional[str]] = {}
            for route in routes:
                reason = skip_reason(event, route)
                chat_id = route["chat_id"]
                if chat_id not in targets or reason is None:
                    targets[chat_id] = reason
            return targets

    if settings.default_chat_id:
        return {settings.default_chat_id: None}

    return {}


async def _resolve_chats(repos: Repositories, event: ParsedEvent) -> list[int]:
    """Chat ids that would receive the event (filters applied)."""
    return [chat for chat, reason in (await _resolve_targets(repos, event)).items() if reason is None]


class SendResult:
    __slots__ = ("message_id", "error")

    def __init__(self, message_id: Optional[int] = None, error: Optional[str] = None) -> None:
        self.message_id = message_id
        self.error = error

    @property
    def ok(self) -> bool:
        return self.message_id is not None


async def _send_to_chat(
    bot: Bot, chat_id: int, text: str, reply_to: Optional[int] = None
) -> SendResult:
    """
    Send a message, honouring Telegram rate limits and retrying transient
    failures with exponential backoff. `reply_to` threads the message under an
    earlier post (the original is allowed to be gone).
    """
    reply = (
        ReplyParameters(message_id=reply_to, allow_sending_without_reply=True)
        if reply_to
        else None
    )
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            sent = await bot.send_message(chat_id, text, reply_parameters=reply)
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
    chat_id: int,
    result: SendResult,
    text: str,
    status: Optional[str] = None,
) -> None:
    try:
        await repos.deliveries.record(
            chat_id=chat_id,
            resource=event.resource,
            action=event.action,
            project=event.project_slug or (str(event.project_ref_id) if event.project_ref_id else None),
            environment=event.environment,
            issue_id=event.issue_id,
            title=event.title,
            status=status or ("sent" if result.ok else "failed"),
            error=result.error,
            tg_message_id=result.message_id,
            text=text if result.ok else None,
        )
    except Exception:
        log.exception("Could not record delivery for chat_id=%s", chat_id)


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
    except TelegramRetryAfter as exc:
        log.debug("Rate limited while stamping message %s; skipping", prior["tg_message_id"])
    except Exception as exc:  # noqa: BLE001 — purely cosmetic, never fail delivery
        log.debug("Could not stamp original message %s: %s", prior["tg_message_id"], exc)


async def send_event(bot: Bot, repos: Repositories, event: ParsedEvent) -> None:
    """Resolve routing and deliver the formatted event to all matched chats."""
    targets = await _resolve_targets(repos, event)
    if not targets:
        log.warning(
            "No target chats for resource=%s action=%s project=%s env=%s",
            event.resource,
            event.action,
            event.project_slug or event.project_ref_id,
            event.environment,
        )
        return

    text = format_event(event)
    for chat_id, reason in targets.items():
        if reason is not None:
            log.info("Skipping chat_id=%s for %s.%s: %s", chat_id, event.resource, event.action, reason)
            await _record(repos, event, chat_id, SendResult(error=reason), text, status="skipped")
            continue
        prior: Optional[dict] = None
        if event.issue_id:
            try:
                prior = await repos.deliveries.last_for_issue(chat_id, event.issue_id)
            except Exception:
                log.exception("Thread lookup failed for chat_id=%s", chat_id)
        result = await _send_to_chat(
            bot, chat_id, text, reply_to=prior["tg_message_id"] if prior else None
        )
        await _record(repos, event, chat_id, result, text)
        if prior and result.ok:
            await _stamp_original(bot, repos, event, chat_id, prior)


async def delivery_worker(
    queue: "asyncio.Queue[Optional[ParsedEvent]]", bot: Bot, repos: Repositories
) -> None:
    """
    Background asyncio task that consumes ParsedEvent items and delivers them.
    Putting None into the queue triggers a clean shutdown.
    """
    log.info("Delivery worker started")
    while True:
        item = await queue.get()
        if item is None:
            log.info("Delivery worker: shutdown sentinel received")
            queue.task_done()
            break
        try:
            await send_event(bot, repos, item)
        except Exception:
            log.exception("Unhandled error in delivery worker")
        finally:
            queue.task_done()
    log.info("Delivery worker stopped")
