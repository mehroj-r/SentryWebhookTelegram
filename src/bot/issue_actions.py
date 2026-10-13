"""
Inline Resolve / Ignore / Assign-to-me / Open buttons on issue alerts.

Buttons appear only when a Sentry Web API token covers the event's
organisation (SENTRY_API_TOKEN(S)). Callback data can be forged by any
client, so a click is honoured only when this chat really received an alert
for that issue and the user passes the usual admin check.
"""
from __future__ import annotations

import logging
import re
from html import escape
from typing import Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..config import settings
from ..db import Repositories
from ..i18n import t
from ..sentry.api import SentryAPI, pick_org
from ..sentry.formatters import _safe_url, status_footer
from ..sentry.parser import ParsedEvent
from .keyboards import key_for, resolve_key
from .middlewares import AdminMiddleware, LanguageMiddleware

log = logging.getLogger(__name__)

_RESOURCES = frozenset({"issue", "error", "event_alert"})
# Lifecycle states after which the buttons are kept on the (stamped) original.
KEEP_BUTTONS_ACTIONS = frozenset({"assigned", "unresolved"})
_SENTRY_USER_RE = re.compile(r"^[\w.@+\-]{1,128}$")


class IssueCallback(CallbackData, prefix="iss"):
    action: str  # r = resolve, i = ignore, a = assign to me
    issue: str   # numeric Sentry issue id
    org: str     # key_for(org)


_ACTIONS = {
    "r": ({"status": "resolved"}, "issue.done_resolve", "issue.resolve"),
    "i": ({"status": "ignored"}, "issue.done_ignore", "issue.ignore"),
}


def issue_keyboard(event: ParsedEvent, lang: str, *, stamping: bool = False) -> Optional[InlineKeyboardMarkup]:
    """
    Buttons for the first alert about an issue (or, with `stamping`, for the
    original message being re-edited after an assign/unresolve). None when
    the event isn't about an issue or no API token covers its org.
    """
    if event.resource not in _RESOURCES or not (event.issue_id or "").isdigit():
        return None
    if not stamping and status_footer(event) is not None:
        return None  # lifecycle update: it's posted as a threaded reply, no buttons
    org = pick_org(settings.sentry_api_orgs, event.org)
    if org is None:
        return None
    builder = InlineKeyboardBuilder()
    for action, label in (("r", "btn.resolve"), ("i", "btn.ignore"), ("a", "btn.assign")):
        builder.button(
            text=t(lang, label),
            callback_data=IssueCallback(action=action, issue=event.issue_id, org=key_for(org)),
        )
    if url := _safe_url(event.web_url):
        builder.button(text=t(lang, "btn.open"), url=url)
    builder.adjust(2)
    return builder.as_markup()


issue_router = Router(name="issue_actions")
issue_router.message.outer_middleware(LanguageMiddleware())
issue_router.callback_query.outer_middleware(LanguageMiddleware())
issue_router.callback_query.middleware(AdminMiddleware())


@issue_router.callback_query(IssueCallback.filter())
async def on_issue_action(
    callback: CallbackQuery,
    callback_data: IssueCallback,
    repos: Repositories,
    sentry_api: SentryAPI,
    lang: str,
) -> None:
    if callback.message is None:
        await callback.answer(t(lang, "issue.unknown"), show_alert=True)
        return
    chat_id = callback.message.chat.id
    org = resolve_key(callback_data.org, sentry_api.orgs)
    if org is None:
        await callback.answer(t(lang, "issue.no_api"), show_alert=True)
        return
    # Forged callbacks: only act on issues this chat was actually alerted about.
    if await repos.deliveries.last_for_issue(chat_id, callback_data.issue) is None:
        await callback.answer(t(lang, "issue.unknown"), show_alert=True)
        return

    if callback_data.action == "a":
        who = await repos.identities.get(callback.from_user.id)
        if who is None:
            await callback.answer(t(lang, "issue.need_identity"), show_alert=True)
            return
        payload, done_key, audit_action = {"assignedTo": who}, "issue.done_assign", "issue.assign"
    elif callback_data.action in _ACTIONS:
        payload, done_key, audit_action = _ACTIONS[callback_data.action]
    else:
        await callback.answer()
        return

    ok, error = await sentry_api.update_issue(org, callback_data.issue, payload)
    if not ok:
        await callback.answer(t(lang, "issue.failed", error=error), show_alert=True)
        return
    try:
        await repos.audit.record(
            chat_id, callback.from_user.id, audit_action, f"{org}/{callback_data.issue}"
            + (f" → {payload['assignedTo']}" if "assignedTo" in payload else "")
        )
    except Exception:  # noqa: BLE001
        log.exception("failed to audit %s", audit_action)
    await callback.answer(t(lang, done_key))


@issue_router.message(Command("sentry_user"))
async def cmd_sentry_user(message: Message, repos: Repositories, lang: str) -> None:
    """/sentry_user [<username|email>|off] — who "Assign to me" assigns to."""
    if message.from_user is None:
        return
    parts = (message.text or "").split()[1:]
    if not parts:
        who = await repos.identities.get(message.from_user.id)
        if who:
            await message.answer(t(lang, "sentry_user.current", user=escape(who)))
        else:
            await message.answer(t(lang, "sentry_user.none"))
        return
    if len(parts) != 1 or not (parts[0].lower() == "off" or _SENTRY_USER_RE.match(parts[0])):
        await message.answer(t(lang, "sentry_user.usage"))
        return
    if parts[0].lower() == "off":
        await repos.identities.set(message.from_user.id, None)
        await message.answer(t(lang, "sentry_user.cleared"))
        return
    await repos.identities.set(message.from_user.id, parts[0])
    await message.answer(t(lang, "sentry_user.set", user=escape(parts[0])))
