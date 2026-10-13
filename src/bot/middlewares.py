from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Optional

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from ..config import settings

_DENIED_MSG = "⛔ You are not allowed to do that."


def is_admin(user_id: Optional[int]) -> bool:
    """ADMIN_IDS membership; an empty ADMIN_IDS means open access."""
    return not settings.admin_ids or user_id in settings.admin_ids


class AdminMiddleware(BaseMiddleware):
    """
    Short-circuit any handler on this router if the user is not in ADMIN_IDS.

    When ADMIN_IDS is empty every user is allowed (open access mode).
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        from_user = getattr(event, "from_user", None)
        if not is_admin(from_user.id if from_user else None):
            if isinstance(event, Message):
                await event.answer(_DENIED_MSG)
            elif isinstance(event, CallbackQuery):
                await event.answer(_DENIED_MSG, show_alert=True)
            return None  # do NOT call the handler

        return await handler(event, data)
