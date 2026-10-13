import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import settings
from src.selfcheck import self_check

EXPECTED_URL = settings.webhook_base_url + settings.tg_webhook_path


def _bot(url=EXPECTED_URL, last_error=None, chat_error=None):
    bot = MagicMock()
    bot.get_me = AsyncMock(return_value=MagicMock(username="sentry_bot", id=1))
    bot.get_webhook_info = AsyncMock(return_value=MagicMock(
        url=url, last_error_message=last_error,
        last_error_date=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc) if last_error else None,
        pending_update_count=0,
    ))
    bot.get_chat = AsyncMock(
        side_effect=chat_error, return_value=MagicMock(id=-100, title="Ops")
    )
    return bot


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.setattr(settings, "use_webhook", True)
    monkeypatch.setattr(settings, "default_chat_id", None)


async def test_all_good(repos, caplog):
    await repos.routes.add("backend", None, -100)
    with caplog.at_level(logging.INFO):
        assert await self_check(_bot(), repos) == []
    assert "Self-check passed" in caplog.text
    assert "1 route(s) across 1 chat(s)" in caplog.text


async def test_reports_problems(repos, monkeypatch, caplog):
    monkeypatch.setattr(settings, "default_chat_id", -555)
    bot = _bot(url="https://old.example/hook", last_error="Connection refused", chat_error=RuntimeError("chat not found"))
    warnings = await self_check(bot, repos)
    assert any("expected" in w and "old.example" in w for w in warnings)
    assert any("Connection refused" in w and "2026-10-01 12:00" in w for w in warnings)
    assert any("DEFAULT_CHAT_ID -555" in w for w in warnings)
    assert "Self-check:" in caplog.text


async def test_no_routes_no_default(repos):
    [w] = await self_check(_bot(), repos)
    assert "will not be delivered" in w


async def test_polling_mode_skips_webhook_and_never_raises(repos, monkeypatch):
    monkeypatch.setattr(settings, "use_webhook", False)
    await repos.routes.add("backend", None, -100)
    bot = _bot()
    bot.get_me = AsyncMock(side_effect=RuntimeError("Unauthorized"))
    [w] = await self_check(bot, repos)
    assert "BOT_TOKEN" in w
    bot.get_webhook_info.assert_not_awaited()
