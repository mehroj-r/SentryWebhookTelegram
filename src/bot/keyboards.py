from __future__ import annotations

import hashlib

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Telegram caps callback_data at 64 bytes. Sentry project slugs (≤50 chars) and
# environment names (≤64 chars) can't be embedded verbatim, so callbacks carry a
# short stable hash and handlers resolve it against the current project /
# environment lists.
ANY_ENV = "ANY"
_HASH_LEN = 12


def key_for(value: str) -> str:
    """Short, stable identifier for a slug or environment name."""
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:_HASH_LEN]


def resolve_key(key: str, candidates: list[str]) -> str | None:
    """Reverse `key_for` by scanning `candidates`."""
    for candidate in candidates:
        if key_for(candidate) == key:
            return candidate
    return None


class ProjectCallback(CallbackData, prefix="proj"):
    key: str  # key_for(project_slug)


class EnvCallback(CallbackData, prefix="env"):
    project_key: str  # key_for(project_slug)
    env_key: str      # key_for(environment) or ANY_ENV for "any environment"


class DelRouteCallback(CallbackData, prefix="del"):
    route_id: int


def _button_label(text: str, limit: int = 60) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def projects_keyboard(projects: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for p in projects:
        label = p.get("name") or p["slug"]
        builder.button(
            text=_button_label(label),
            callback_data=ProjectCallback(key=key_for(p["slug"])),
        )
    builder.adjust(2)
    return builder.as_markup()


def environments_keyboard(project: str, environments: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    project_key = key_for(project)
    for env in environments:
        builder.button(
            text=_button_label(env),
            callback_data=EnvCallback(project_key=project_key, env_key=key_for(env)),
        )
    builder.button(
        text="🌐 Any environment",
        callback_data=EnvCallback(project_key=project_key, env_key=ANY_ENV),
    )
    builder.adjust(2)
    return builder.as_markup()


def routes_keyboard(routes: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for r in routes:
        env_label = r["environment"] or "any env"
        builder.button(
            text=_button_label(f"✖️ {r['project']} / {env_label}"),
            callback_data=DelRouteCallback(route_id=r["id"]),
        )
    builder.adjust(1)
    return builder.as_markup()
