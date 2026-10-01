from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from html import escape
from typing import Optional

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..db import Repositories
from ..filters import LEVELS, normalize_level, parse_actions, parse_duration
from .keyboards import (
    ANY_ENV,
    DelRouteCallback,
    EnvCallback,
    ProjectCallback,
    environments_keyboard,
    projects_keyboard,
    resolve_key,
    routes_keyboard,
)
from .middlewares import AdminMiddleware

log = logging.getLogger(__name__)

# Sentry slugs: lowercase letters, digits, '-' and '_' (we're lenient on case).
# Project key: "slug", "org/slug" (multi-org) or a wildcard pattern ("backend-*", "*").
_SLUG_RE = re.compile(r"^(?:[A-Za-z0-9_\-.*]{1,64}/)?[A-Za-z0-9_\-.*]{1,64}$")
_ROUTES_PROMPT = "Routes for this chat — tap a button to remove it:"


def _route_label(project: str, environment: Optional[str]) -> str:
    """HTML-safe '<b>project</b> / env' label built from user-supplied text."""
    return f"<b>{escape(project)}</b> / {escape(environment or 'any environment')}"


async def _safe_edit(callback: CallbackQuery, text: str, **kwargs) -> None:
    """
    Edit the message a callback came from. `callback.message` is None or an
    InaccessibleMessage when the message is too old / deleted, in which case
    we fall back to a fresh message in the same chat (if we know it).
    """
    msg = callback.message
    if isinstance(msg, Message):
        try:
            await msg.edit_text(text, **kwargs)
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc):
                return
            log.warning("edit_text failed, sending new message: %s", exc)
            await msg.answer(text, **kwargs)
            return
    if msg is not None:  # InaccessibleMessage still knows its chat
        await callback.bot.send_message(msg.chat.id, text, **kwargs)


# ── public router — anyone can use these ───────────────────────────────────────
public_router = Router(name="public")


@public_router.message(Command("start", "help"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 <b>Sentry → Telegram Bot</b>\n\n"
        "I forward Sentry webhook events to Telegram chats.\n\n"
        "<b>Commands:</b>\n"
        "• /subscribe — route Sentry events to this chat\n"
        "• /routes — view and remove routing rules for this chat\n"
        "• /add_route &lt;slug|pattern&gt; [env] — add a route (wildcards: backend-*, *)\n"
        "• /filter &lt;slug|all&gt; level=&lt;min&gt; actions=&lt;a,b&gt; — noise control\n"
        "• /mute &lt;30m|2h|1d&gt; [slug] and /unmute [slug] — pause alerts\n"
        "• /digest &lt;slug|all&gt; &lt;minutes|off&gt; — batch events into periodic digests\n"
        "• /last — show the last events delivered to this chat\n"
        "• /chat_id — show this chat's id (for DEFAULT_CHAT_ID)\n"
        "• /help — show this message",
    )


@public_router.message(Command("chat_id"))
async def cmd_chat_id(message: Message) -> None:
    await message.answer(f"This chat's id: <code>{message.chat.id}</code>")


@public_router.message(Command("routes"))
async def cmd_routes(message: Message, repos: Repositories) -> None:
    routes = await repos.routes.list_for_chat(message.chat.id)
    if not routes:
        await message.answer(
            "No routing rules for this chat. Use /subscribe or /add_route to add one."
        )
        return
    await message.answer(_ROUTES_PROMPT, reply_markup=routes_keyboard(routes))


_STATUS_ICON = {"sent": "✅", "failed": "❌", "skipped": "⏭"}


@public_router.message(Command("last"))
async def cmd_last(message: Message, repos: Repositories) -> None:
    rows = await repos.deliveries.recent_for_chat(message.chat.id, limit=10)
    if not rows:
        await message.answer("Nothing has been delivered to this chat yet.")
        return
    lines = ["<b>Last deliveries to this chat:</b>"]
    for r in rows:
        when = r["created_at"].strftime("%m-%d %H:%M") if r["created_at"] else "?"
        icon = _STATUS_ICON.get(r["status"], "•")
        where = escape(r["project"] or "?")
        if r["environment"]:
            where += f"/{escape(r['environment'])}"
        line = f"{icon} <code>{when}</code> {escape(r['resource'])}.{escape(r['action'])} {where}: {escape(r['title'][:60])}"
        if r["error"]:
            line += f"\n    ↳ <i>{escape(r['error'][:120])}</i>"
        lines.append(line)
    await message.answer("\n".join(lines))


# ── admin router — gated by AdminMiddleware ────────────────────────────────────
admin_router = Router(name="admin")
admin_router.message.middleware(AdminMiddleware())
admin_router.callback_query.middleware(AdminMiddleware())


@admin_router.message(Command("subscribe"))
async def cmd_subscribe(message: Message, repos: Repositories) -> None:
    projects = await repos.projects.list_all()
    if not projects:
        await message.answer(
            "No Sentry projects seen yet.\n\n"
            "Once Sentry sends the first webhook event the project will appear here.\n\n"
            "You can also add a route right now with:\n"
            "<code>/add_route &lt;project-slug&gt; [environment]</code>",
        )
        return
    await message.answer(
        "Select a Sentry project to route to this chat:",
        reply_markup=projects_keyboard(projects),
    )


@admin_router.callback_query(ProjectCallback.filter())
async def on_project_selected(
    callback: CallbackQuery,
    callback_data: ProjectCallback,
    repos: Repositories,
) -> None:
    projects = await repos.projects.list_all()
    project = resolve_key(callback_data.key, [p["slug"] for p in projects])
    if project is None:
        await callback.answer("Unknown project — run /subscribe again.", show_alert=True)
        return

    envs = await repos.environments.list_for_project(project)
    await _safe_edit(
        callback,
        f"Project: <b>{escape(project)}</b>\n\nChoose an environment:",
        reply_markup=environments_keyboard(project, envs),
    )
    await callback.answer()


@admin_router.callback_query(EnvCallback.filter())
async def on_env_selected(
    callback: CallbackQuery,
    callback_data: EnvCallback,
    repos: Repositories,
) -> None:
    if callback.message is None:
        await callback.answer("This menu has expired — run /subscribe again.", show_alert=True)
        return

    projects = await repos.projects.list_all()
    project = resolve_key(callback_data.project_key, [p["slug"] for p in projects])
    if project is None:
        await callback.answer("Unknown project — run /subscribe again.", show_alert=True)
        return

    environment: Optional[str] = None
    if callback_data.env_key != ANY_ENV:
        envs = await repos.environments.list_for_project(project)
        environment = resolve_key(callback_data.env_key, envs)
        if environment is None:
            await callback.answer("Unknown environment — run /subscribe again.", show_alert=True)
            return

    chat_id = callback.message.chat.id
    inserted = await repos.routes.add(
        project, environment, chat_id, created_by=callback.from_user.id
    )
    label = _route_label(project, environment)
    text = (
        f"✅ Route added: {label} → this chat."
        if inserted
        else f"ℹ️ Route already exists: {label} → this chat."
    )
    await _safe_edit(callback, text)
    await callback.answer()


@admin_router.message(Command("add_route"))
async def cmd_add_route(message: Message, repos: Repositories) -> None:
    """Manual route: /add_route <project-slug> [environment]"""
    parts = (message.text or "").split()[1:]
    usage = "Usage: <code>/add_route &lt;project-slug&gt; [environment]</code>"
    if not parts or len(parts) > 2:
        await message.answer(usage)
        return

    project = parts[0]
    environment: Optional[str] = parts[1] if len(parts) > 1 else None
    if not _SLUG_RE.match(project) or (environment and len(environment) > 64):
        await message.answer(
            "Invalid project slug or environment.\n" + usage
        )
        return

    created_by = message.from_user.id if message.from_user else None
    inserted = await repos.routes.add(
        project, environment, message.chat.id, created_by=created_by
    )
    label = _route_label(project, environment)
    if inserted:
        await message.answer(f"✅ Route added: {label} → this chat.")
    else:
        await message.answer(f"ℹ️ Route already exists: {label} → this chat.")


_FILTER_USAGE = (
    "Usage: <code>/filter &lt;project-slug|all&gt; [level=&lt;min&gt;] [actions=&lt;a,b&gt;]</code>\n"
    "or <code>/filter &lt;project-slug|all&gt; clear</code>\n\n"
    f"Levels: {', '.join(LEVELS)}. Actions e.g. created,resolved,assigned."
)


@admin_router.message(Command("filter"))
async def cmd_filter(message: Message, repos: Repositories) -> None:
    """Set min level / allowed actions on this chat's routes."""
    parts = (message.text or "").split()[1:]
    if not parts:
        await message.answer(_FILTER_USAGE)
        return
    project: Optional[str] = None if parts[0].lower() == "all" else parts[0]
    if project and not _SLUG_RE.match(project):
        await message.answer(_FILTER_USAGE)
        return

    opts = parts[1:]
    if opts == ["clear"]:
        n = await repos.routes.set_filters(message.chat.id, project, min_level=None, actions=None)
        await message.answer(f"🧹 Filters cleared on {n} route(s).")
        return

    kwargs: dict = {}
    for opt in opts:
        key, _, value = opt.partition("=")
        if key == "level":
            level = normalize_level(value)
            if level is None:
                await message.answer(f"Unknown level <code>{escape(value)}</code>.\n" + _FILTER_USAGE)
                return
            kwargs["min_level"] = level
        elif key == "actions":
            actions = parse_actions(value)
            if not actions or any(not re.match(r"^[a-z_]+$", a) for a in actions):
                await message.answer(_FILTER_USAGE)
                return
            kwargs["actions"] = ",".join(actions)
        else:
            await message.answer(_FILTER_USAGE)
            return
    if not kwargs:
        await message.answer(_FILTER_USAGE)
        return

    n = await repos.routes.set_filters(message.chat.id, project, **kwargs)
    if n == 0:
        await message.answer("No matching routes in this chat. Add one first with /subscribe.")
        return
    desc = " ".join(f"{k.replace('min_', '')}={escape(v)}" for k, v in kwargs.items())
    await message.answer(f"🔧 Updated {n} route(s): <code>{desc}</code>")


@admin_router.message(Command("mute"))
async def cmd_mute(message: Message, repos: Repositories) -> None:
    """/mute <duration> [project-slug] — pause deliveries to this chat."""
    parts = (message.text or "").split()[1:]
    usage = "Usage: <code>/mute &lt;30m|2h|1d&gt; [project-slug]</code>"
    if not parts or len(parts) > 2:
        await message.answer(usage)
        return
    duration = parse_duration(parts[0])
    if duration is None or duration.total_seconds() <= 0:
        await message.answer(usage)
        return
    project = parts[1] if len(parts) > 1 else None
    if project and not _SLUG_RE.match(project):
        await message.answer(usage)
        return
    until = datetime.now(timezone.utc) + duration
    n = await repos.routes.set_filters(message.chat.id, project, muted_until=until)
    if n == 0:
        await message.answer("No matching routes in this chat.")
        return
    await message.answer(
        f"🔇 Muted {n} route(s) until <code>{until:%Y-%m-%d %H:%M} UTC</code>. Use /unmute to resume."
    )


@admin_router.message(Command("digest"))
async def cmd_digest(message: Message, repos: Repositories) -> None:
    """/digest <slug|all> <minutes|off> — switch routes between instant and digest mode."""
    parts = (message.text or "").split()[1:]
    usage = "Usage: <code>/digest &lt;project-slug|all&gt; &lt;minutes|off&gt;</code>  (e.g. /digest all 60)"
    if len(parts) != 2:
        await message.answer(usage)
        return
    project: Optional[str] = None if parts[0].lower() == "all" else parts[0]
    if project and not _SLUG_RE.match(project):
        await message.answer(usage)
        return
    if parts[1].lower() == "off":
        minutes: Optional[int] = None
    else:
        if not parts[1].isdigit() or not (1 <= int(parts[1]) <= 24 * 60):
            await message.answer("Minutes must be between 1 and 1440.\n" + usage)
            return
        minutes = int(parts[1])
    n = await repos.routes.set_filters(message.chat.id, project, digest_minutes=minutes)
    if n == 0:
        await message.answer("No matching routes in this chat.")
        return
    if minutes is None:
        await message.answer(f"⚡ {n} route(s) switched back to instant delivery.")
    else:
        await message.answer(f"📰 {n} route(s) will now send a digest every {minutes} min.")


@admin_router.message(Command("unmute"))
async def cmd_unmute(message: Message, repos: Repositories) -> None:
    parts = (message.text or "").split()[1:]
    project = parts[0] if parts else None
    if project and not _SLUG_RE.match(project):
        await message.answer("Usage: <code>/unmute [project-slug]</code>")
        return
    n = await repos.routes.set_filters(message.chat.id, project, muted_until=None)
    await message.answer(f"🔔 Unmuted {n} route(s).")


@admin_router.callback_query(DelRouteCallback.filter())
async def on_del_route(
    callback: CallbackQuery,
    callback_data: DelRouteCallback,
    repos: Repositories,
) -> None:
    if callback.message is None:
        await callback.answer("This menu has expired — run /routes again.", show_alert=True)
        return

    chat_id = callback.message.chat.id
    removed = await repos.routes.remove(callback_data.route_id, chat_id)
    remaining = await repos.routes.list_for_chat(chat_id)
    if remaining:
        await _safe_edit(callback, _ROUTES_PROMPT, reply_markup=routes_keyboard(remaining))
    else:
        await _safe_edit(callback, "✅ All routes removed for this chat.")
    await callback.answer("Route removed." if removed else "Route was already gone.")
