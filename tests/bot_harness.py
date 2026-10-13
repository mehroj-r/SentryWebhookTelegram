"""Drive aiogram handlers end to end with a fake Telegram session."""
from __future__ import annotations

import datetime as dt
import itertools

from aiogram import Bot, Dispatcher
from aiogram.client.telegram import PRODUCTION
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageText,
    GetChatMember,
    GetFile,
    SendDocument,
    SendMessage,
    TelegramMethod,
)
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    Chat,
    ChatMemberAdministrator,
    ChatMemberMember,
    ChatMemberOwner,
    Document,
    File,
    Message,
    Update,
    User,
)

from src.bot.handlers import admin_router, public_router

ADMIN = User(id=1, is_bot=False, first_name="Admin")
OTHER = User(id=42, is_bot=False, first_name="Other")
GROUP = Chat(id=-100500, type="supergroup", title="Ops")


class FakeSession:
    api = PRODUCTION

    def __init__(self) -> None:
        self.calls: list[TelegramMethod] = []
        self._ids = itertools.count(1000)
        self.files: dict[str, bytes] = {}  # file_id → content, served by GetFile + stream_content
        # (chat_id, user_id) → "creator" | "administrator" | "member" | "error"; default member
        self.members: dict[tuple[int, int], str] = {}

    async def __call__(self, bot: Bot, method: TelegramMethod, timeout=None):  # noqa: ANN001
        self.calls.append(method)
        if isinstance(method, SendMessage):
            return Message(
                message_id=next(self._ids), date=dt.datetime.now(),
                chat=Chat(id=method.chat_id, type="supergroup"), text=method.text,
            )
        if isinstance(method, EditMessageText):
            return True
        if isinstance(method, GetChatMember):
            return _member(method, self.members.get((method.chat_id, method.user_id), "member"))
        if isinstance(method, GetFile):
            return File(file_id=method.file_id, file_unique_id=method.file_id, file_path=method.file_id)
        return True

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):  # noqa: ANN001
        yield self.files[url.rsplit("/", 1)[-1]]

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
    def documents(self) -> list[SendDocument]:
        return [c for c in self.calls if isinstance(c, SendDocument)]

    @property
    def last_text(self) -> str:
        return self.sent[-1].text if self.sent else ""


def _member(method: GetChatMember, status: str):  # noqa: ANN202
    user = User(id=method.user_id, is_bot=False, first_name="U")
    if status == "error":
        raise TelegramBadRequest(method=method, message="Bad Request: chat not found")
    if status == "creator":
        return ChatMemberOwner(user=user, is_anonymous=False)
    if status == "administrator":
        # Every required permission flag (the set grows with Telegram API versions).
        flags = {
            name: False
            for name, f in ChatMemberAdministrator.model_fields.items()
            if f.is_required() and name not in ("status", "user")
        }
        return ChatMemberAdministrator(user=user, **flags)
    return ChatMemberMember(user=user)


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

    async def command(
        self,
        text: str,
        user: User = ADMIN,
        chat: Chat = GROUP,
        *,
        reply_to: Message | None = None,
        document: bytes | None = None,
        sender_chat: Chat | None = None,
    ) -> None:
        """Send `text` as a command; with `document` it becomes the caption of an uploaded file."""
        cmd_len = len(text.split()[0])
        entities = [{"type": "bot_command", "offset": 0, "length": cmd_len}]
        if document is not None:
            fields = {"document": self.upload(document), "caption": text, "caption_entities": entities}
        else:
            fields = {"text": text, "entities": entities}
        message = Message(
            message_id=next(self._msg_ids), date=dt.datetime.now(), chat=chat, from_user=user,
            reply_to_message=reply_to, sender_chat=sender_chat, **fields,
        )
        await self.dp.feed_update(self.bot, Update(update_id=next(self._update_ids), message=message))

    def upload(self, content: bytes, file_size: int | None = None) -> Document:
        file_id = f"file{next(self._msg_ids)}"
        self.session.files[file_id] = content
        return Document(file_id=file_id, file_unique_id=file_id, file_name="routes.json",
                        file_size=len(content) if file_size is None else file_size)

    def message(self, chat: Chat = GROUP, *, text: str | None = None, document: Document | None = None) -> Message:
        """A plain message to reply to."""
        return Message(message_id=next(self._msg_ids), date=dt.datetime.now(), chat=chat, text=text, document=document)

    async def callback(self, data: str, user: User = ADMIN, chat: Chat = GROUP) -> None:
        message = Message(message_id=next(self._msg_ids), date=dt.datetime.now(), chat=chat, text="menu")
        cq = CallbackQuery(id="cq", from_user=user, chat_instance="ci", message=message, data=data)
        await self.dp.feed_update(self.bot, Update(update_id=next(self._update_ids), callback_query=cq))
