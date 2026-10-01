from __future__ import annotations

import asyncio
import logging
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)

from .config import settings
from .db import Repositories
from .sentry.formatters import format_event
from .sentry.parser import ParsedEvent

log = logging.getLogger(__name__)

_MAX_ATTEMPTS = 5
_BACKOFF_BASE_S = 1.0
_BACKOFF_MAX_S = 30.0


async def _resolve_chats(repos: Repositories, event: ParsedEvent) -> list[int]:
    """
    Return target chat IDs for a parsed event.

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
        chats = await repos.routes.resolve_chats(project, event.environment)
        if chats:
            return chats

    if settings.default_chat_id:
        return [settings.default_chat_id]

    return []


async def _send_to_chat(bot: Bot, chat_id: int, text: str) -> bool:
    """
    Send a message, honouring Telegram rate limits and retrying transient
    failures with exponential backoff. Returns True on success.
    """
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            await bot.send_message(chat_id, text)
            return True
        except TelegramRetryAfter as exc:
            wait = min(float(exc.retry_after), 120.0)
            log.warning("Rate limited on chat_id=%s; retrying after %.1f s", chat_id, wait)
            await asyncio.sleep(wait)
        except (TelegramNetworkError, TelegramServerError) as exc:
            if attempt == _MAX_ATTEMPTS:
                log.error("Giving up on chat_id=%s after %d attempts: %s", chat_id, attempt, exc)
                return False
            wait = min(_BACKOFF_BASE_S * 2 ** (attempt - 1), _BACKOFF_MAX_S)
            log.warning(
                "Transient Telegram error for chat_id=%s (attempt %d/%d): %s; retry in %.0fs",
                chat_id, attempt, _MAX_ATTEMPTS, exc, wait,
            )
            await asyncio.sleep(wait)
        except TelegramForbiddenError as exc:
            # Bot was blocked / kicked from the chat — retrying is pointless.
            log.warning("Not allowed to message chat_id=%s (%s); skipping", chat_id, exc)
            return False
        except TelegramBadRequest as exc:
            # Permanent: chat not found, malformed HTML, etc.
            log.error("Telegram rejected message for chat_id=%s: %s", chat_id, exc)
            return False
        except Exception:
            log.exception("Unexpected error sending to chat_id=%s", chat_id)
            return False
    return False


async def send_event(bot: Bot, repos: Repositories, event: ParsedEvent) -> None:
    """Resolve routing and deliver the formatted event to all matched chats."""
    chats = await _resolve_chats(repos, event)
    if not chats:
        log.warning(
            "No target chats for resource=%s action=%s project=%s env=%s",
            event.resource,
            event.action,
            event.project_slug or event.project_ref_id,
            event.environment,
        )
        return

    text = format_event(event)
    for chat_id in chats:
        await _send_to_chat(bot, chat_id, text)


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
