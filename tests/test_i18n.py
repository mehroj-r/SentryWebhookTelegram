import re
import string
from pathlib import Path

import pytest
from aiogram.types import Chat, User

from src.i18n import CATALOG, LANGUAGES, normalize_language, t
from tests.bot_harness import GROUP, OTHER, Harness

SRC = Path(__file__).resolve().parents[1] / "src"


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


@pytest.mark.parametrize("key", sorted(CATALOG))
def test_catalog_complete_and_consistent(key):
    entry = CATALOG[key]
    assert set(entry) == set(LANGUAGES), f"{key}: missing {set(LANGUAGES) - set(entry)}"
    en = _fields(entry["en"])
    for lang in LANGUAGES:
        assert _fields(entry[lang]) == en, f"{key}/{lang} placeholders differ from en"
        assert entry[lang].strip()


def test_every_key_used_in_code_exists():
    used = set()
    for path in SRC.rglob("*.py"):
        used |= set(re.findall(r"""\bt\(\s*[\w.]+\s*,\s*["']([\w.]+)["']""", path.read_text()))
    assert used, "regex found no t() calls"
    assert used <= set(CATALOG), used - set(CATALOG)


def test_normalize_and_fallback():
    assert normalize_language("RU") == "ru"
    assert normalize_language("uz-Latn") == "uz"
    assert normalize_language("de") is None and normalize_language(None) is None
    assert t("de", "yes") == "yes" and t(None, "yes") == "yes"
    assert t("ru", "chat_id", chat_id=5) == "Id этого чата: <code>5</code>"


@pytest.fixture
def h(repos):
    return Harness(repos)


async def test_lang_command_switches_replies(h, repos):
    await h.command("/lang de")
    assert "Usage" in h.session.last_text
    await h.command("/lang ru")
    assert "Язык: Русский" in h.session.last_text
    assert (await repos.chat_settings.get(GROUP.id))["language"] == "ru"

    await h.command("/add_route backend")
    assert h.session.last_text.startswith("✅ Маршрут добавлен")
    await h.command("/routes")
    assert h.session.last_text.startswith("Маршруты этого чата")
    assert "любое" in h.session.sent[-1].reply_markup.inline_keyboard[0][0].text

    await h.command("/add_route backend", user=OTHER)  # admin denial is localised too
    assert h.session.last_text == "⛔ У вас нет прав на это действие."

    await h.command("/lang uz")
    await h.command("/help")
    assert "Buyruqlar" in h.session.last_text
    [entry] = [e for e in await repos.audit.recent_for_chat(GROUP.id) if e["details"] == "uz"]
    assert entry["action"] == "settings.lang"


async def test_private_chat_uses_telegram_language(h):
    ru_user = User(id=7, is_bot=False, first_name="Ivan", language_code="ru")
    await h.command("/help", user=ru_user, chat=Chat(id=7, type="private"))
    assert "Команды" in h.session.last_text
    # ...but not in groups, where members may speak different languages
    await h.command("/help", user=ru_user, chat=GROUP)
    assert "Commands" in h.session.last_text


async def test_chat_setting_beats_user_language(h, repos):
    await repos.chat_settings.update(7, language="uz")
    ru_user = User(id=7, is_bot=False, first_name="Ivan", language_code="ru")
    await h.command("/help", user=ru_user, chat=Chat(id=7, type="private"))
    assert "Buyruqlar" in h.session.last_text
