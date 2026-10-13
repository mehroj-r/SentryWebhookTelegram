"""
Startup self-check: catch configuration mistakes early and say so in the log
instead of silently dropping alerts later. Never raises.
"""
from __future__ import annotations

import logging

from aiogram import Bot

from .config import settings
from .db import Repositories

log = logging.getLogger(__name__)


async def self_check(bot: Bot, repos: Repositories) -> list[str]:
    """Log a startup summary; return the warnings found (also logged)."""
    warnings: list[str] = []

    try:
        me = await bot.get_me()
        log.info("Bot: @%s (id %s)", me.username, me.id)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"get_me failed — is BOT_TOKEN valid? ({exc})")

    if settings.use_webhook:
        expected = settings.webhook_base_url + settings.tg_webhook_path
        try:
            info = await bot.get_webhook_info()
            if info.url != expected:
                warnings.append(f"Telegram webhook is {info.url or '(none)'!r}, expected {expected!r}")
            if info.last_error_message:
                when = f" at {info.last_error_date:%Y-%m-%d %H:%M} UTC" if info.last_error_date else ""
                warnings.append(f"Telegram reports a webhook delivery error{when}: {info.last_error_message}")
            if info.pending_update_count:
                log.info("Telegram has %d pending update(s) for us", info.pending_update_count)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"get_webhook_info failed ({exc})")

    if settings.default_chat_id is not None:
        try:
            chat = await bot.get_chat(settings.default_chat_id)
            log.info("DEFAULT_CHAT_ID %s: %s", chat.id, chat.title or chat.full_name or chat.type)
        except Exception as exc:  # noqa: BLE001
            warnings.append(
                f"DEFAULT_CHAT_ID {settings.default_chat_id} is not reachable — add the bot to it? ({exc})"
            )

    try:
        routes = await repos.routes.list_all()
        projects = await repos.projects.list_all()
        installations = await repos.installations.list_all()
        log.info(
            "Routing: %d route(s) across %d chat(s); %d project(s) seen; %d installation(s)",
            len(routes), len({r["chat_id"] for r in routes}), len(projects), len(installations),
        )
        if not routes and settings.default_chat_id is None:
            warnings.append(
                "No routes and no DEFAULT_CHAT_ID: incoming Sentry events will not be delivered anywhere. "
                "Run /subscribe in a chat or set DEFAULT_CHAT_ID."
            )
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Could not read routing tables ({exc})")

    for w in warnings:
        log.warning("Self-check: %s", w)
    if not warnings:
        log.info("Self-check passed")
    return warnings
