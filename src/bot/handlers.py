from __future__ import annotations

import fnmatch
import logging
import re
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Optional

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Document, Message, User

from ..chat_settings import format_local, parse_quiet_range, parse_timezone
from ..db import Repositories
from ..delivery import retry_failed
from ..filters import LEVELS, normalize_level, parse_actions, parse_duration, skip_reason
from ..i18n import LANGUAGE_NAMES, normalize_language, t
from ..route_io import MAX_BYTES, SLUG_RE as _SLUG_RE, export_routes, parse_import
from ..samples import KINDS as SAMPLE_KINDS, sample_event
from ..sentry.formatters import format_event, strip_html
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
from .middlewares import AdminMiddleware, LanguageMiddleware, is_admin

log = logging.getLogger(__name__)

def _topic_of(message: Message) -> Optional[int]:
    """Forum topic id when the message was sent inside a topic (General topic → None)."""
    if getattr(message, "is_topic_message", False) and message.message_thread_id:
        return message.message_thread_id
    return None


def _route_label(project: str, environment: Optional[str], lang: str) -> str:
    """HTML-safe '<b>project</b> / env' label built from user-supplied text."""
    return f"<b>{escape(project)}</b> / {escape(environment or t(lang, 'route.any_env'))}"


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
public_router.message.outer_middleware(LanguageMiddleware())
public_router.callback_query.outer_middleware(LanguageMiddleware())


@public_router.message(Command("start", "help"))
async def cmd_start(message: Message, lang: str) -> None:
    await message.answer(t(lang, "help"))


@public_router.message(Command("chat_id"))
async def cmd_chat_id(message: Message, lang: str) -> None:
    await message.answer(t(lang, "chat_id", chat_id=message.chat.id))


@public_router.message(Command("routes"))
async def cmd_routes(message: Message, repos: Repositories, lang: str) -> None:
    args = (message.text or "").split()[1:]
    if args and args[0].lower() in ("verbose", "-v"):
        await message.answer(await _routes_verbose(message.chat.id, repos, lang))
        return
    routes = await repos.routes.list_for_chat(message.chat.id)
    if not routes:
        await message.answer(t(lang, "routes.none"))
        return
    await message.answer(t(lang, "routes.prompt"), reply_markup=routes_keyboard(routes, lang))


def _route_details(r: dict, prefs: Optional[dict], lang: str) -> str:
    parts = []
    if r["min_level"]:
        parts.append(f"level≥{escape(r['min_level'])}")
    if r["actions"]:
        parts.append(f"actions={escape(r['actions'])}")
    if r["digest_minutes"]:
        parts.append(t(lang, "route.digest", n=r["digest_minutes"]))
    if r["thread_id"]:
        parts.append(t(lang, "route.topic", id=r["thread_id"]))
    muted = r["muted_until"]
    if muted is not None:
        if muted.tzinfo is None:
            muted = muted.replace(tzinfo=timezone.utc)
        if muted > datetime.now(timezone.utc):
            parts.append(t(lang, "route.muted", when=format_local(muted, prefs)))
    added = t(lang, "route.added_at", when=format_local(r["created_at"], prefs) if r["created_at"] else "?")
    if r["created_by"]:
        added += t(lang, "route.by", user=r["created_by"])
    parts.append(added)
    return f"• {_route_label(r['project'], r['environment'], lang)}\n    " + ", ".join(parts)


async def _routes_verbose(chat_id: int, repos: Repositories, lang: str) -> str:
    routes = await repos.routes.list_for_chat(chat_id)
    prefs = await repos.chat_settings.get(chat_id)
    lines = [t(lang, "routes.verbose_title", n=len(routes))]
    lines += [_route_details(r, prefs, lang) for r in routes] or [t(lang, "none")]
    entries = await repos.audit.recent_for_chat(chat_id, limit=10)
    if entries:
        lines.append("\n" + t(lang, "routes.recent_changes"))
        for e in entries:
            who = f"<code>{e['user_id']}</code>" if e["user_id"] else "?"
            line = f"<code>{format_local(e['ts'], prefs)}</code> {who} {escape(e['action'])}"
            if e["details"]:
                line += f": {escape(e['details'][:200])}"
            lines.append(line)
    return "\n".join(lines)


@public_router.message(Command("whoami"))
async def cmd_whoami(message: Message, lang: str) -> None:
    user = message.from_user
    lines = []
    if user:
        name = escape(user.full_name) + (f" (@{escape(user.username)})" if user.username else "")
        lines.append(t(lang, "whoami.user", name=name, id=user.id))
        admin = await is_admin(message.bot, message.chat, user.id, message.sender_chat)
        lines.append(t(lang, "whoami.admin", answer=t(lang, "yes" if admin else "no")))
    lines.append(t(lang, "whoami.chat", id=message.chat.id, type=escape(message.chat.type)))
    topic = _topic_of(message)
    if topic:
        lines.append(t(lang, "whoami.topic", id=topic))
    await message.answer("\n".join(lines))


_STATUS_ICON = {"sent": "✅", "failed": "❌", "skipped": "⏭", "digest": "📰", "retried": "🔁"}


@public_router.message(Command("last"))
async def cmd_last(message: Message, repos: Repositories, lang: str) -> None:
    rows = await repos.deliveries.recent_for_chat(message.chat.id, limit=10)
    if not rows:
        await message.answer(t(lang, "last.empty"))
        return
    prefs = await repos.chat_settings.get(message.chat.id)
    lines = [t(lang, "last.title")]
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


# "retried" rows are superseded by the retry's own row, so they aren't counted.
_STATS_STATUSES = ("sent", "failed", "skipped", "digest")
_STATS_TOP = 10


def _stats_line(lang: str, period_key: str, by_project: dict[str, dict[str, int]]) -> str:
    totals = {s: sum(p.get(s, 0) for p in by_project.values()) for s in _STATS_STATUSES}
    breakdown = ", ".join(
        f"{_STATUS_ICON[s]} {totals[s]} {t(lang, 'status.' + s)}" for s in _STATS_STATUSES if totals[s]
    )
    return t(lang, "stats.period", period=t(lang, period_key), total=sum(totals.values()), breakdown=breakdown or "—")


@public_router.message(Command("stats"))
async def cmd_stats(message: Message, repos: Repositories, lang: str) -> None:
    now = datetime.now(timezone.utc)
    week = await repos.deliveries.counts_by_project(message.chat.id, now - timedelta(days=7))
    if not any(sum(v.get(s, 0) for s in _STATS_STATUSES) for v in week.values()):
        await message.answer(t(lang, "stats.empty"))
        return
    day = await repos.deliveries.counts_by_project(message.chat.id, now - timedelta(hours=24))
    lines = [t(lang, "stats.title"), _stats_line(lang, "stats.24h", day), _stats_line(lang, "stats.7d", week)]

    def _total(counts: dict[str, int]) -> int:
        return sum(counts.get(s, 0) for s in _STATS_STATUSES)

    ranked = sorted(((p, c) for p, c in week.items() if _total(c)), key=lambda pc: (-_total(pc[1]), pc[0]))
    lines += ["", t(lang, "stats.top")]
    for project, counts in ranked[:_STATS_TOP]:
        extras = " ".join(f"{_STATUS_ICON[s]}{counts[s]}" for s in ("failed", "skipped", "digest") if counts.get(s))
        day_total = _total(day.get(project, {}))
        lines.append(
            f"• <code>{escape(project)}</code> — {_total(counts)} (24h: {day_total})" + (f"  {extras}" if extras else "")
        )
    await message.answer("\n".join(lines))


# ── admin router — gated by AdminMiddleware ────────────────────────────────────
admin_router = Router(name="admin")
admin_router.message.outer_middleware(LanguageMiddleware())
admin_router.callback_query.outer_middleware(LanguageMiddleware())
admin_router.message.middleware(AdminMiddleware())
admin_router.callback_query.middleware(AdminMiddleware())


@admin_router.message(Command("subscribe"))
async def cmd_subscribe(message: Message, repos: Repositories, lang: str) -> None:
    projects = await repos.projects.list_all()
    if not projects:
        await message.answer(t(lang, "subscribe.no_projects"))
        return
    await message.answer(t(lang, "subscribe.prompt"), reply_markup=projects_keyboard(projects))


@admin_router.callback_query(ProjectCallback.filter())
async def on_project_selected(
    callback: CallbackQuery,
    callback_data: ProjectCallback,
    repos: Repositories,
    lang: str,
) -> None:
    projects = await repos.projects.list_all()
    project = resolve_key(callback_data.key, [p["slug"] for p in projects])
    if project is None:
        await callback.answer(t(lang, "subscribe.unknown_project"), show_alert=True)
        return

    envs = await repos.environments.list_for_project(project)
    await _safe_edit(
        callback,
        t(lang, "subscribe.choose_env", project=escape(project)),
        reply_markup=environments_keyboard(project, envs, lang),
    )
    await callback.answer()


@admin_router.callback_query(EnvCallback.filter())
async def on_env_selected(
    callback: CallbackQuery,
    callback_data: EnvCallback,
    repos: Repositories,
    lang: str,
) -> None:
    if callback.message is None:
        await callback.answer(t(lang, "subscribe.expired"), show_alert=True)
        return

    projects = await repos.projects.list_all()
    project = resolve_key(callback_data.project_key, [p["slug"] for p in projects])
    if project is None:
        await callback.answer(t(lang, "subscribe.unknown_project"), show_alert=True)
        return

    environment: Optional[str] = None
    if callback_data.env_key != ANY_ENV:
        envs = await repos.environments.list_for_project(project)
        environment = resolve_key(callback_data.env_key, envs)
        if environment is None:
            await callback.answer(t(lang, "subscribe.unknown_env"), show_alert=True)
            return

    chat_id = callback.message.chat.id
    thread_id = _topic_of(callback.message) if isinstance(callback.message, Message) else None
    inserted = await repos.routes.add(
        project, environment, chat_id, created_by=callback.from_user.id, thread_id=thread_id
    )
    if inserted:
        await _audit(repos, chat_id, callback.from_user, "route.add", _plain_route(project, environment))
    label = _route_label(project, environment, lang)
    text = t(lang, "route.added" if inserted else "route.exists", label=label)
    await _safe_edit(callback, text)
    await callback.answer()


@admin_router.message(Command("add_route"))
async def cmd_add_route(message: Message, repos: Repositories, lang: str) -> None:
    """Manual route: /add_route <project-slug> [environment]"""
    parts = (message.text or "").split()[1:]
    usage = t(lang, "add_route.usage")
    if not parts or len(parts) > 2:
        await message.answer(usage)
        return

    project = parts[0]
    environment: Optional[str] = parts[1] if len(parts) > 1 else None
    if not _SLUG_RE.match(project) or (environment and len(environment) > 64):
        await message.answer(t(lang, "add_route.invalid", usage=usage))
        return

    created_by = message.from_user.id if message.from_user else None
    inserted = await repos.routes.add(
        project, environment, message.chat.id, created_by=created_by, thread_id=_topic_of(message)
    )
    label = _route_label(project, environment, lang)
    if inserted:
        await _audit(repos, message.chat.id, message.from_user, "route.add", _plain_route(project, environment))
    await message.answer(t(lang, "route.added" if inserted else "route.exists", label=label))


@admin_router.message(Command("filter"))
async def cmd_filter(message: Message, repos: Repositories, lang: str) -> None:
    """Set min level / allowed actions on this chat's routes."""
    usage = t(lang, "filter.usage", levels=", ".join(LEVELS))
    parts = (message.text or "").split()[1:]
    if not parts:
        await message.answer(usage)
        return
    project: Optional[str] = None if parts[0].lower() == "all" else parts[0]
    if project and not _SLUG_RE.match(project):
        await message.answer(usage)
        return

    opts = parts[1:]
    if opts == ["clear"]:
        n = await repos.routes.set_filters(message.chat.id, project, min_level=None, actions=None)
        if n:
            await _audit(repos, message.chat.id, message.from_user, "filter.clear", project or "all")
        await message.answer(t(lang, "filter.cleared", n=n))
        return

    kwargs: dict = {}
    for opt in opts:
        key, _, value = opt.partition("=")
        if key == "level":
            level = normalize_level(value)
            if level is None:
                await message.answer(t(lang, "filter.unknown_level", value=escape(value), usage=usage))
                return
            kwargs["min_level"] = level
        elif key == "actions":
            actions = parse_actions(value)
            if not actions or any(not re.match(r"^[a-z_]+$", a) for a in actions):
                await message.answer(usage)
                return
            kwargs["actions"] = ",".join(actions)
        else:
            await message.answer(usage)
            return
    if not kwargs:
        await message.answer(usage)
        return

    n = await repos.routes.set_filters(message.chat.id, project, **kwargs)
    if n == 0:
        await message.answer(t(lang, "filter.no_routes"))
        return
    plain = " ".join(f"{k.replace('min_', '')}={v}" for k, v in kwargs.items())
    await _audit(repos, message.chat.id, message.from_user, "filter", f"{project or 'all'} {plain}")
    desc = " ".join(f"{k.replace('min_', '')}={escape(v)}" for k, v in kwargs.items())
    await message.answer(t(lang, "filter.updated", n=n, desc=desc))


@admin_router.message(Command("mute"))
async def cmd_mute(message: Message, repos: Repositories, lang: str) -> None:
    """/mute <duration> [project-slug] — pause deliveries to this chat."""
    parts = (message.text or "").split()[1:]
    usage = t(lang, "mute.usage")
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
        await message.answer(t(lang, "no_matching_routes"))
        return
    await _audit(repos, message.chat.id, message.from_user, "mute", f"{project or 'all'} for {parts[0]}")
    await message.answer(t(lang, "mute.done", n=n, until=f"{until:%Y-%m-%d %H:%M}"))


@admin_router.message(Command("digest"))
async def cmd_digest(message: Message, repos: Repositories, lang: str) -> None:
    """/digest <slug|all> <minutes|off> — switch routes between instant and digest mode."""
    parts = (message.text or "").split()[1:]
    usage = t(lang, "digest.usage")
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
            await message.answer(t(lang, "digest.range", usage=usage))
            return
        minutes = int(parts[1])
    n = await repos.routes.set_filters(message.chat.id, project, digest_minutes=minutes)
    if n == 0:
        await message.answer(t(lang, "no_matching_routes"))
        return
    await _audit(
        repos, message.chat.id, message.from_user, "digest",
        f"{project or 'all'} {'off' if minutes is None else f'{minutes}m'}",
    )
    if minutes is None:
        await message.answer(t(lang, "digest.off", n=n))
    else:
        await message.answer(t(lang, "digest.on", n=n, minutes=minutes))


@admin_router.message(Command("unmute"))
async def cmd_unmute(message: Message, repos: Repositories, lang: str) -> None:
    parts = (message.text or "").split()[1:]
    project = parts[0] if parts else None
    if project and not _SLUG_RE.match(project):
        await message.answer(t(lang, "unmute.usage"))
        return
    n = await repos.routes.set_filters(message.chat.id, project, muted_until=None)
    if n:
        await _audit(repos, message.chat.id, message.from_user, "unmute", project or "all")
    await message.answer(t(lang, "unmute.done", n=n))


def _settings_text(prefs: Optional[dict], lang: str) -> str:
    p = prefs or {}
    quiet = f"{p['quiet_start']}–{p['quiet_end']}" if p.get("quiet_start") and p.get("quiet_end") else t(lang, "off")
    return t(
        lang, "settings.text",
        tz=escape(p.get("timezone") or "UTC"),
        quiet=escape(quiet),
        language=escape(p.get("language") or lang),
        format=escape(p.get("format") or "html"),
    )


@public_router.message(Command("settings"))
async def cmd_settings(message: Message, repos: Repositories, lang: str) -> None:
    await message.answer(_settings_text(await repos.chat_settings.get(message.chat.id), lang))


@admin_router.message(Command("tz"))
async def cmd_tz(message: Message, repos: Repositories, lang: str) -> None:
    parts = (message.text or "").split()[1:]
    if len(parts) != 1:
        await message.answer(t(lang, "tz.usage"))
        return
    tz = parse_timezone(parts[0])
    if tz is None:
        await message.answer(t(lang, "tz.unknown", tz=escape(parts[0])))
        return
    prefs = await repos.chat_settings.update(message.chat.id, timezone=tz)
    await _audit(repos, message.chat.id, message.from_user, "settings.tz", tz)
    await message.answer(t(lang, "tz.set", tz=escape(tz)) + "\n\n" + _settings_text(prefs, lang))


@admin_router.message(Command("lang"))
async def cmd_lang(message: Message, repos: Repositories, lang: str) -> None:
    parts = (message.text or "").split()[1:]
    new = normalize_language(parts[0]) if len(parts) == 1 else None
    if new is None:
        await message.answer(t(lang, "lang.usage"))
        return
    prefs = await repos.chat_settings.update(message.chat.id, language=new)
    await _audit(repos, message.chat.id, message.from_user, "settings.lang", new)
    await message.answer(t(new, "lang.set", name=LANGUAGE_NAMES[new]) + "\n\n" + _settings_text(prefs, new))


@admin_router.message(Command("format"))
async def cmd_format(message: Message, repos: Repositories, lang: str) -> None:
    parts = (message.text or "").split()[1:]
    fmt = parts[0].lower() if len(parts) == 1 else None
    if fmt not in ("html", "plain"):
        await message.answer(t(lang, "format.usage"))
        return
    prefs = await repos.chat_settings.update(message.chat.id, format=fmt)
    await _audit(repos, message.chat.id, message.from_user, "settings.format", fmt)
    await message.answer(t(lang, "format.set", format=fmt) + "\n\n" + _settings_text(prefs, lang))


@admin_router.message(Command("quiet"))
async def cmd_quiet(message: Message, repos: Repositories, lang: str) -> None:
    parts = (message.text or "").split()[1:]
    usage = t(lang, "quiet.usage")
    if len(parts) != 1:
        await message.answer(usage)
        return
    if parts[0].lower() == "off":
        prefs = await repos.chat_settings.update(message.chat.id, quiet_start=None, quiet_end=None)
        await _audit(repos, message.chat.id, message.from_user, "settings.quiet", "off")
        await message.answer(t(lang, "quiet.disabled") + "\n\n" + _settings_text(prefs, lang))
        return
    rng = parse_quiet_range(parts[0])
    if rng is None:
        await message.answer(usage)
        return
    prefs = await repos.chat_settings.update(message.chat.id, quiet_start=rng[0], quiet_end=rng[1])
    await _audit(repos, message.chat.id, message.from_user, "settings.quiet", f"{rng[0]}-{rng[1]}")
    await message.answer(
        t(lang, "quiet.set", start=rng[0], end=rng[1]) + "\n\n" + _settings_text(prefs, lang)
    )


@public_router.message(Command("export"))
async def cmd_export(message: Message, repos: Repositories, lang: str) -> None:
    routes = await repos.routes.list_for_chat(message.chat.id)
    if not routes:
        await message.answer(t(lang, "export.empty"))
        return
    data = export_routes(message.chat.id, routes).encode()
    await message.answer_document(
        BufferedInputFile(data, filename=f"routes-{message.chat.id}.json"),
        caption=t(lang, "export.caption", n=len(routes)),
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
async def cmd_import(message: Message, repos: Repositories, lang: str) -> None:
    reply = message.reply_to_message
    document = message.document or (reply.document if reply else None)
    if document is not None and (document.file_size or 0) > MAX_BYTES:
        await message.answer(t(lang, "import.too_large", kb=MAX_BYTES // 1024))
        return
    text = await _import_source(message, document)
    if text is None:
        await message.answer(t(lang, "import.usage"))
        return

    result = parse_import(text)
    if result.errors:
        shown = "\n".join(f"• {escape(e)}" for e in result.errors[:10])
        if len(result.errors) > 10:
            shown += "\n" + t(lang, "import.more_errors", n=len(result.errors) - 10)
        await message.answer(t(lang, "import.errors", errors=shown))
        return
    if not result.routes:
        await message.answer(t(lang, "import.empty"))
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
    await message.answer(t(lang, "import.done", n=len(result.routes), added=added, updated=updated))


def _sample_target(routes: list[dict]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """(org, project, environment) of this chat's first concrete route, for realistic samples."""
    for r in routes:
        if "*" not in r["project"]:
            org, _, slug = r["project"].rpartition("/")
            return org or None, slug, r["environment"]
    return None, None, None


@admin_router.message(Command("test"))
async def cmd_test(message: Message, repos: Repositories, lang: str) -> None:
    """/test [kind] — format a sample event and post it here (or in this topic)."""
    parts = (message.text or "").split()[1:]
    kind = parts[0].lower() if parts else "issue"
    if len(parts) > 1 or kind not in SAMPLE_KINDS:
        await message.answer(t(lang, "test.usage", kinds="|".join(SAMPLE_KINDS)))
        return

    routes = await repos.routes.list_for_chat(message.chat.id)
    org, project, environment = _sample_target(routes)
    event = sample_event(kind, project, environment)
    event.org = org
    text = format_event(event, lang)
    prefs = await repos.chat_settings.get(message.chat.id)
    if (prefs or {}).get("format") == "plain":
        await message.answer(strip_html(text), parse_mode=None)
    else:
        await message.answer(text)

    if not routes:
        verdict = t(lang, "test.no_routes")
    else:
        key = f"{org}/{event.project_slug}" if org else event.project_slug
        matching = [r for r in routes if fnmatch.fnmatchcase(key, r["project"])]
        reasons = [skip_reason(event, r) for r in matching] or [t(lang, "test.no_match")]
        if any(reason is None for reason in reasons):
            verdict = t(lang, "test.deliver")
        else:
            verdict = t(lang, "test.skip", reason=escape(reasons[0], quote=False))
    await message.answer(t(lang, "test.footer", verdict=verdict))


@admin_router.message(Command("retry_failed"))
async def cmd_retry_failed(message: Message, repos: Repositories, lang: str) -> None:
    """/retry_failed [N] — re-send this chat's last N failed deliveries (default 10, max 50)."""
    parts = (message.text or "").split()[1:]
    usage = t(lang, "retry.usage")
    if len(parts) > 1 or (parts and not (parts[0].isdigit() and 1 <= int(parts[0]) <= 50)):
        await message.answer(usage)
        return
    limit = int(parts[0]) if parts else 10
    if not await repos.deliveries.retryable(message.chat.id, limit=1):
        await message.answer(t(lang, "retry.nothing"))
        return
    sent, failed = await retry_failed(message.bot, repos, message.chat.id, limit)
    await _audit(repos, message.chat.id, message.from_user, "retry_failed", f"{sent} sent, {failed} failed")
    key = "retry.done_failed" if failed else "retry.done"
    await message.answer(t(lang, key, total=sent + failed, sent=sent, failed=failed))


@admin_router.callback_query(DelRouteCallback.filter())
async def on_del_route(
    callback: CallbackQuery,
    callback_data: DelRouteCallback,
    repos: Repositories,
    lang: str,
) -> None:
    if callback.message is None:
        await callback.answer(t(lang, "del.expired"), show_alert=True)
        return

    chat_id = callback.message.chat.id
    target = next((r for r in await repos.routes.list_for_chat(chat_id) if r["id"] == callback_data.route_id), None)
    removed = await repos.routes.remove(callback_data.route_id, chat_id)
    if removed and target:
        await _audit(repos, chat_id, callback.from_user, "route.remove", _plain_route(target["project"], target["environment"]))
    remaining = await repos.routes.list_for_chat(chat_id)
    if remaining:
        await _safe_edit(callback, t(lang, "routes.prompt"), reply_markup=routes_keyboard(remaining, lang))
    else:
        await _safe_edit(callback, t(lang, "del.all_removed"))
    await callback.answer(t(lang, "del.removed" if removed else "del.gone"))
