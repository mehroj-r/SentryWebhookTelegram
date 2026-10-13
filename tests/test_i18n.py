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
        # literal keys only (followed by "," or ")"); dynamic ones like "status." + s are tested by use
        used |= set(re.findall(r"""\bt\(\s*[\w.]+\s*,\s*["']([\w.]+)["']\s*[,)]""", path.read_text()))
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


# ── event formatting ───────────────────────────────────────────────────────────

from unittest.mock import AsyncMock, MagicMock  # noqa: E402

from src.burst import Summary  # noqa: E402
from src.delivery import flush_digests, send_burst_summary, send_event  # noqa: E402
from src.i18n import plural  # noqa: E402
from src.samples import sample_event  # noqa: E402
from src.sentry.formatters import format_digest, format_event, status_footer  # noqa: E402


def test_plural_rules():
    assert [plural("ru", "w.events", n) for n in (1, 2, 5, 11, 21, 22, 112)] == [
        "событие", "события", "событий", "событий", "событие", "события", "событий"]
    assert plural("en", "w.events", 1) == "event" and plural("en", "w.events", 0) == "events"
    assert plural("uz", "w.events", 7) == "ta hodisa"


def test_formatter_labels_localised():
    issue = sample_event("issue")
    assert "<b>Issue CREATED</b>" in format_event(issue)
    assert "<b>Проблема CREATED</b>" in format_event(issue, "ru")
    assert "Daraja: <b>error</b>" in format_event(issue, "uz")
    assert "Commits: 12" in format_event(sample_event("release"))
    assert "Коммиты: 12" in format_event(sample_event("release"), "ru")
    assert format_digest([{"project": "p", "title": "x"}] * 5, lang="ru").startswith(
        "📰 <b>Сводка</b>: 5 событий в 1 проблеме")
    issue.action, issue.actor = "resolved", "Al"
    assert status_footer(issue, "uz") == "✅ <b>RESOLVED</b> (Al)"


async def test_send_event_renders_once_per_language(repos, monkeypatch):
    from src import delivery

    for chat in (10, 20, 30):
        await repos.routes.add("p", None, chat)
    await repos.chat_settings.update(20, language="ru")
    await repos.chat_settings.update(30, language="ru")
    calls = []
    real = delivery.format_event
    monkeypatch.setattr(delivery, "format_event", lambda e, lang="en": calls.append(lang) or real(e, lang))

    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    event = sample_event("issue", "p")
    event.issue_id = None
    await send_event(bot, repos, event)
    sent = {c.args[0]: c.args[1] for c in bot.send_message.await_args_list}
    assert "Issue CREATED" in sent[10]
    assert "Проблема CREATED" in sent[20] and sent[20] == sent[30]
    assert sorted(calls) == ["en", "ru"]


async def test_digest_and_burst_use_chat_language(repos):
    await repos.chat_settings.update(10, language="uz")
    await repos.routes.add("p", None, 10)
    [route] = await repos.routes.list_for_chat(10)
    await repos.digests.add(chat_id=10, route_id=route["id"], project="p", environment=None, issue_id="1",
                            resource="issue", action="created", level="error", title="T", web_url=None)
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    await flush_digests(bot, repos, force=True)
    assert bot.send_message.await_args.args[1].startswith("📰 <b>Jamlanma</b>: 1 ta hodisa")

    await send_burst_summary(bot, repos, Summary(chat_id=10, issue_id="1", count=4, window_s=600,
                                                 sample=sample_event("error", "p")))
    assert "Yana +4" in bot.send_message.await_args.args[1]
