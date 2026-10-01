"""Drive aiogram handlers end to end with a fake Telegram session."""
from __future__ import annotations

import datetime as dt
import itertools

from aiogram import Bot, Dispatcher
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage, TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from src.bot.handlers import admin_router, public_router

ADMIN = User(id=1, is_bot=False, first_name="Admin")
OTHER = User(id=42, is_bot=False, first_name="Other")
GROUP = Chat(id=-100500, type="supergroup", title="Ops")


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[TelegramMethod] = []
        self._ids = itertools.count(1000)

    async def __call__(self, bot: Bot, method: TelegramMethod, timeout=None):  # noqa: ANN001
        self.calls.append(method)
        if isinstance(method, SendMessage):
            return Message(
                message_id=next(self._ids), date=dt.datetime.now(),
                chat=Chat(id=method.chat_id, type="supergroup"), text=method.text,
            )
        if isinstance(method, EditMessageText):
            return True
        return True

    async def close(self) -> None:
        pass

    @property
    def sent(self) -> list[SendMessage]:
        return [c for c in self.calls if isinstance(c, SendMessage)]

    @property
    def edits(self) -> list[EditMessageText]:
        return [c for c in self.calls if isinstance(c, EditMessageText)]

    @property
    def answers(self) -> list[AnswerCallbackQuery]:
        return [c for c in self.calls if isinstance(c, AnswerCallbackQuery)]

    @property
    def last_text(self) -> str:
        return self.sent[-1].text if self.sent else ""


_DP: Dispatcher | None = None


def _dispatcher() -> Dispatcher:
    """Routers can be attached to one Dispatcher only, so share it across tests."""
    global _DP
    if _DP is None:
        _DP = Dispatcher()
        _DP.include_router(public_router)
        _DP.include_router(admin_router)
    return _DP


class Harness:
    def __init__(self, repos) -> None:  # noqa: ANN001
        self.session = FakeSession()
        self.bot = Bot("123:TEST")
        self.bot.session = self.session  # type: ignore[assignment]
        self.dp = _dispatcher()
        self.dp["repos"] = repos
        self._update_ids = itertools.count(1)
        self._msg_ids = itertools.count(1)

    async def command(self, text: str, user: User = ADMIN, chat: Chat = GROUP) -> None:
        cmd_len = len(text.split()[0])
        message = Message(
            message_id=next(self._msg_ids), date=dt.datetime.now(), chat=chat, from_user=user, text=text,
            entities=[{"type": "bot_command", "offset": 0, "length": cmd_len}],
        )
        await self.dp.feed_update(self.bot, Update(update_id=next(self._update_ids), message=message))

    async def callback(self, data: str, user: User = ADMIN, chat: Chat = GROUP) -> None:
        message = Message(message_id=next(self._msg_ids), date=dt.datetime.now(), chat=chat, text="menu")
        cq = CallbackQuery(id="cq", from_user=user, chat_instance="ci", message=message, data=data)
        await self.dp.feed_update(self.bot, Update(update_id=next(self._update_ids), callback_query=cq))
