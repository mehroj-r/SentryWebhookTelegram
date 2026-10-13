from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from html import escape
from typing import Optional

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Document, Message, User

from ..chat_settings import format_local, parse_quiet_range, parse_timezone
from ..db import Repositories
from ..filters import LEVELS, normalize_level, parse_actions, parse_duration
from ..route_io import MAX_BYTES, SLUG_RE as _SLUG_RE, export_routes, parse_import
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
from .middlewares import AdminMiddleware, is_admin

log = logging.getLogger(__name__)

_ROUTES_PROMPT = "Routes for this chat — tap a button to remove it:"


def _topic_of(message: Message) -> Optional[int]:
    """Forum topic id when the message was sent inside a topic (General topic → None)."""
    if getattr(message, "is_topic_message", False) and message.message_thread_id:
        return message.message_thread_id
    return None


def _route_label(project: str, environment: Optional[str]) -> str:
    """HTML-safe '<b>project</b> / env' label built from user-supplied text."""
    return f"<b>{escape(project)}</b> / {escape(environment or 'any environment')}"


async def _audit(
    repos: Repositories, chat_id: int, user: Optional[User], action: str, details: Optional[str] = None
) -> None:
    """Record a configuration change; never let audit failures break the command."""
    try:
        await repos.audit.record(chat_id, user.id if user else None, action, details)
    except Exception:  # noqa: BLE001
        log.exception("failed to write audit entry %s for chat %s", action, chat_id)


def _plain_route(project: str, environment: Optional[str]) -> str:
    return f"{project} / {environment or '*'}"


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
        "• /routes — view and remove routing rules; /routes verbose — details + recent changes\n"
        "• /add_route &lt;slug|pattern&gt; [env] — add a route (wildcards: backend-*, *)\n"
        "• /filter &lt;slug|all&gt; level=&lt;min&gt; actions=&lt;a,b&gt; — noise control\n"
        "• /mute &lt;30m|2h|1d&gt; [slug] and /unmute [slug] — pause alerts\n"
        "• /digest &lt;slug|all&gt; &lt;minutes|off&gt; — batch events into periodic digests\n"
        "• /settings, /tz &lt;Area/City&gt;, /quiet &lt;22:00-08:00|off&gt; — chat preferences\n"
        "• Run /subscribe or /add_route inside a forum topic to post there\n"
        "• /export — download this chat's routes as JSON; /import — load them (attach or reply to the file)\n"
        "• /last — show the last events delivered to this chat\n"
        "• /chat_id — show this chat's id (for DEFAULT_CHAT_ID); /whoami — your id and permissions\n"
        "• /help — show this message",
    )


@public_router.message(Command("chat_id"))
async def cmd_chat_id(message: Message) -> None:
    await message.answer(f"This chat's id: <code>{message.chat.id}</code>")


@public_router.message(Command("routes"))
async def cmd_routes(message: Message, repos: Repositories) -> None:
    args = (message.text or "").split()[1:]
    if args and args[0].lower() in ("verbose", "-v"):
        await message.answer(await _routes_verbose(message.chat.id, repos))
        return
    routes = await repos.routes.list_for_chat(message.chat.id)
    if not routes:
        await message.answer(
            "No routing rules for this chat. Use /subscribe or /add_route to add one."
        )
        return
    await message.answer(_ROUTES_PROMPT, reply_markup=routes_keyboard(routes))


def _route_details(r: dict, prefs: Optional[dict]) -> str:
    parts = []
    if r["min_level"]:
        parts.append(f"level≥{escape(r['min_level'])}")
    if r["actions"]:
        parts.append(f"actions={escape(r['actions'])}")
    if r["digest_minutes"]:
        parts.append(f"digest {r['digest_minutes']}m")
    if r["thread_id"]:
        parts.append(f"topic {r['thread_id']}")
    muted = r["muted_until"]
    if muted is not None:
        if muted.tzinfo is None:
            muted = muted.replace(tzinfo=timezone.utc)
        if muted > datetime.now(timezone.utc):
            parts.append(f"🔇 until {format_local(muted, prefs)}")
    added = f"added {format_local(r['created_at'], prefs)}" if r["created_at"] else "added ?"
    if r["created_by"]:
        added += f" by <code>{r['created_by']}</code>"
    parts.append(added)
    return f"• {_route_label(r['project'], r['environment'])}\n    " + ", ".join(parts)


async def _routes_verbose(chat_id: int, repos: Repositories) -> str:
    routes = await repos.routes.list_for_chat(chat_id)
    prefs = await repos.chat_settings.get(chat_id)
    lines = [f"<b>Routes for this chat ({len(routes)}):</b>"]
    lines += [_route_details(r, prefs) for r in routes] or ["<i>none</i>"]
    entries = await repos.audit.recent_for_chat(chat_id, limit=10)
    if entries:
        lines.append("\n<b>Recent changes:</b>")
        for e in entries:
            who = f"<code>{e['user_id']}</code>" if e["user_id"] else "?"
            line = f"<code>{format_local(e['ts'], prefs)}</code> {who} {escape(e['action'])}"
            if e["details"]:
                line += f": {escape(e['details'][:200])}"
            lines.append(line)
    return "\n".join(lines)


@public_router.message(Command("whoami"))
async def cmd_whoami(message: Message) -> None:
    user = message.from_user
    lines = []
    if user:
        name = escape(user.full_name) + (f" (@{escape(user.username)})" if user.username else "")
        lines.append(f"👤 {name}\nUser id: <code>{user.id}</code>")
        lines.append("🔑 Admin: " + ("yes" if is_admin(user.id) else "no"))
    lines.append(f"💬 Chat id: <code>{message.chat.id}</code> ({escape(message.chat.type)})")
    topic = _topic_of(message)
    if topic:
        lines.append(f"🧵 Topic id: <code>{topic}</code>")
    await message.answer("\n".join(lines))


_STATUS_ICON = {"sent": "✅", "failed": "❌", "skipped": "⏭"}


@public_router.message(Command("last"))
async def cmd_last(message: Message, repos: Repositories) -> None:
    rows = await repos.deliveries.recent_for_chat(message.chat.id, limit=10)
    if not rows:
        await message.answer("Nothing has been delivered to this chat yet.")
        return
    prefs = await repos.chat_settings.get(message.chat.id)
    lines = ["<b>Last deliveries to this chat:</b>"]
    for r in rows:
        when = format_local(r["created_at"], prefs) if r["created_at"] else "?"
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
    thread_id = _topic_of(callback.message) if isinstance(callback.message, Message) else None
    inserted = await repos.routes.add(
        project, environment, chat_id, created_by=callback.from_user.id, thread_id=thread_id
    )
    if inserted:
        await _audit(repos, chat_id, callback.from_user, "route.add", _plain_route(project, environment))
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
        project, environment, message.chat.id, created_by=created_by, thread_id=_topic_of(message)
    )
    label = _route_label(project, environment)
    if inserted:
        await _audit(repos, message.chat.id, message.from_user, "route.add", _plain_route(project, environment))
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
        if n:
            await _audit(repos, message.chat.id, message.from_user, "filter.clear", project or "all")
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
    plain = " ".join(f"{k.replace('min_', '')}={v}" for k, v in kwargs.items())
    await _audit(repos, message.chat.id, message.from_user, "filter", f"{project or 'all'} {plain}")
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
    await _audit(repos, message.chat.id, message.from_user, "mute", f"{project or 'all'} for {parts[0]}")
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
    await _audit(
        repos, message.chat.id, message.from_user, "digest",
        f"{project or 'all'} {'off' if minutes is None else f'{minutes}m'}",
    )
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
    if n:
        await _audit(repos, message.chat.id, message.from_user, "unmute", project or "all")
    await message.answer(f"🔔 Unmuted {n} route(s).")


def _settings_text(prefs: Optional[dict]) -> str:
    p = prefs or {}
    quiet = f"{p['quiet_start']}–{p['quiet_end']}" if p.get("quiet_start") and p.get("quiet_end") else "off"
    return (
        "<b>Chat settings</b>\n"
        f"🕒 Timezone: <code>{escape(p.get('timezone') or 'UTC')}</code>\n"
        f"🌙 Quiet hours: <code>{escape(quiet)}</code> (fatal events still delivered)\n"
        f"🗣 Language: <code>{escape(p.get('language') or 'en')}</code>\n"
        f"📝 Format: <code>{escape(p.get('format') or 'html')}</code>\n\n"
        "Change with /tz &lt;Area/City&gt;, /quiet &lt;22:00-08:00|off&gt;"
    )


@public_router.message(Command("settings"))
async def cmd_settings(message: Message, repos: Repositories) -> None:
    await message.answer(_settings_text(await repos.chat_settings.get(message.chat.id)))


@admin_router.message(Command("tz"))
async def cmd_tz(message: Message, repos: Repositories) -> None:
    parts = (message.text or "").split()[1:]
    if len(parts) != 1:
        await message.answer("Usage: <code>/tz Asia/Tashkent</code>")
        return
    tz = parse_timezone(parts[0])
    if tz is None:
        await message.answer(f"Unknown timezone <code>{escape(parts[0])}</code>. Use an IANA name like Europe/Berlin.")
        return
    prefs = await repos.chat_settings.update(message.chat.id, timezone=tz)
    await _audit(repos, message.chat.id, message.from_user, "settings.tz", tz)
    await message.answer(f"🕒 Timezone set to <code>{escape(tz)}</code>.\n\n" + _settings_text(prefs))


@admin_router.message(Command("quiet"))
async def cmd_quiet(message: Message, repos: Repositories) -> None:
    parts = (message.text or "").split()[1:]
    usage = "Usage: <code>/quiet 22:00-08:00</code> or <code>/quiet off</code> (times in the chat's timezone)"
    if len(parts) != 1:
        await message.answer(usage)
        return
    if parts[0].lower() == "off":
        prefs = await repos.chat_settings.update(message.chat.id, quiet_start=None, quiet_end=None)
        await _audit(repos, message.chat.id, message.from_user, "settings.quiet", "off")
        await message.answer("🔔 Quiet hours disabled.\n\n" + _settings_text(prefs))
        return
    rng = parse_quiet_range(parts[0])
    if rng is None:
        await message.answer(usage)
        return
    prefs = await repos.chat_settings.update(message.chat.id, quiet_start=rng[0], quiet_end=rng[1])
    await _audit(repos, message.chat.id, message.from_user, "settings.quiet", f"{rng[0]}-{rng[1]}")
    await message.answer(
        f"🌙 Quiet hours set: <code>{rng[0]}–{rng[1]}</code>. Non-fatal events are held and sent as a digest when they end.\n\n"
        + _settings_text(prefs)
    )


@public_router.message(Command("export"))
async def cmd_export(message: Message, repos: Repositories) -> None:
    routes = await repos.routes.list_for_chat(message.chat.id)
    if not routes:
        await message.answer("No routing rules to export in this chat.")
        return
    data = export_routes(message.chat.id, routes).encode()
    await message.answer_document(
        BufferedInputFile(data, filename=f"routes-{message.chat.id}.json"),
        caption=f"📦 {len(routes)} route(s). Send this file with the caption /import (or reply /import to it) in any chat to load them.",
    )


_IMPORT_USAGE = (
    "Usage: send an exported JSON file with the caption <code>/import</code>, "
    "reply <code>/import</code> to such a file, or paste the JSON after the command."
)


async def _import_source(message: Message, document: Optional[Document]) -> Optional[str]:
    """JSON text from: attached/replied-to document, inline after /import, or replied-to text."""
    reply = message.reply_to_message
    if document is not None:
        buf = await message.bot.download(document)
        return buf.read().decode("utf-8", errors="replace") if buf else None
    _, _, inline = (message.text or message.caption or "").partition(" ")
    if inline.strip():
        return inline
    if reply is not None and reply.text:
        return reply.text
    return None


@admin_router.message(Command("import"))
async def cmd_import(message: Message, repos: Repositories) -> None:
    reply = message.reply_to_message
    document = message.document or (reply.document if reply else None)
    if document is not None and (document.file_size or 0) > MAX_BYTES:
        await message.answer(f"❌ File is larger than {MAX_BYTES // 1024} KB.")
        return
    text = await _import_source(message, document)
    if text is None:
        await message.answer(_IMPORT_USAGE)
        return

    result = parse_import(text)
    if result.errors:
        shown = "\n".join(f"• {escape(e)}" for e in result.errors[:10])
        more = f"\n…and {len(result.errors) - 10} more" if len(result.errors) > 10 else ""
        await message.answer(f"❌ Nothing imported:\n{shown}{more}")
        return
    if not result.routes:
        await message.answer("The document contains no routes.")
        return

    # Topic ids only mean something in the chat they came from. Elsewhere,
    # post into the topic /import was sent from (or the main chat).
    if result.source_chat_id != message.chat.id:
        topic = _topic_of(message)
        for r in result.routes:
            r["thread_id"] = topic

    created_by = message.from_user.id if message.from_user else None
    added, updated = await repos.routes.import_routes(message.chat.id, result.routes, created_by)
    await _audit(
        repos, message.chat.id, message.from_user, "routes.import",
        f"{len(result.routes)} route(s): {added} added, {updated} updated",
    )
    await message.answer(f"📥 Imported {len(result.routes)} route(s): {added} added, {updated} updated.")


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
    target = next((r for r in await repos.routes.list_for_chat(chat_id) if r["id"] == callback_data.route_id), None)
    removed = await repos.routes.remove(callback_data.route_id, chat_id)
    if removed and target:
        await _audit(repos, chat_id, callback.from_user, "route.remove", _plain_route(target["project"], target["environment"]))
    remaining = await repos.routes.list_for_chat(chat_id)
    if remaining:
        await _safe_edit(callback, _ROUTES_PROMPT, reply_markup=routes_keyboard(remaining))
    else:
        await _safe_edit(callback, "✅ All routes removed for this chat.")
    await callback.answer("Route removed." if removed else "Route was already gone.")
