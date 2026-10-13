from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Optional

from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Chat, Message, TelegramObject

from ..config import settings

log = logging.getLogger(__name__)

_DENIED_MSG = "⛔ You are not allowed to do that."
_ADMIN_STATUSES = {"creator", "administrator"}
ADMIN_CACHE_SECONDS = 300

# (chat_id, user_id) → (expires_at monotonic, is_admin)
_member_cache: dict[tuple[int, int], tuple[float, bool]] = {}


def clear_admin_cache() -> None:
    _member_cache.clear()


async def _is_chat_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    key = (chat_id, user_id)
    now = time.monotonic()
    cached = _member_cache.get(key)
    if cached and cached[0] > now:
        return cached[1]
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        result = member.status in _ADMIN_STATUSES
    except TelegramAPIError as exc:
        log.warning("get_chat_member(%s, %s) failed: %s", chat_id, user_id, exc)
        return False  # not cached: a transient error shouldn't lock people out for 5 min
    _member_cache[key] = (now + ADMIN_CACHE_SECONDS, result)
    return result


async def is_admin(
    bot: Bot,
    chat: Optional[Chat],
    user_id: Optional[int],
    sender_chat: Optional[Chat] = None,
) -> bool:
    """
    May this user change the bot's configuration in this chat?

    - ADMIN_IDS set: only those users, everywhere.
    - ADMIN_IDS empty: anyone in a private chat; in groups and channels, the
      chat's Telegram admins (status cached for ADMIN_CACHE_SECONDS). Anonymous
      group admins post as the group itself (`sender_chat == chat`).
    """
    if settings.admin_ids:
        return user_id in settings.admin_ids
    if chat is None:
        return False
    if chat.type == "private":
        return True
    if sender_chat is not None and sender_chat.id == chat.id:
        return True
    if user_id is None:
        return False
    return await _is_chat_admin(bot, chat.id, user_id)


class AdminMiddleware(BaseMiddleware):
    """Short-circuit any handler on this router unless `is_admin` allows the sender."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        from_user = getattr(event, "from_user", None)
        user_id = from_user.id if from_user else None
        if isinstance(event, Message):
            chat, sender_chat = event.chat, event.sender_chat
        elif isinstance(event, CallbackQuery):
            msg = event.message
            chat, sender_chat = (msg.chat if msg is not None else None), None
        else:
            chat, sender_chat = None, None

        if not await is_admin(data["bot"], chat, user_id, sender_chat):
            if isinstance(event, Message):
                await event.answer(_DENIED_MSG)
            elif isinstance(event, CallbackQuery):
                await event.answer(_DENIED_MSG, show_alert=True)
            return None  # do NOT call the handler

        return await handler(event, data)
