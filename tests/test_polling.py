import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Bot, Dispatcher
from pydantic import ValidationError

import main
from src.config import Settings, settings
from src.web import build_app

BASE = {"bot_token": "1:x", "sentry_client_secret": "s", "_env_file": None}


def test_webhook_mode_requires_url_and_secret(monkeypatch):
    for var in ("WEBHOOK_BASE_URL", "WEBHOOK_SECRET_TOKEN", "USE_WEBHOOK"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ValidationError, match="USE_WEBHOOK=false"):
        Settings(**BASE)
    with pytest.raises(ValidationError, match="https://"):
        Settings(**BASE, webhook_base_url="http://x", webhook_secret_token="t")
    Settings(**BASE, webhook_base_url="https://x", webhook_secret_token="t")


def test_polling_mode_needs_no_webhook_settings(monkeypatch):
    for var in ("WEBHOOK_BASE_URL", "WEBHOOK_SECRET_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("USE_WEBHOOK", "false")
    s = Settings(**BASE)
    assert s.use_webhook is False and s.webhook_base_url == ""


def _routes(app):
    return {r.resource.canonical for r in app.router.routes()}


def test_build_app_skips_telegram_route_when_polling(monkeypatch):
    monkeypatch.setattr(settings, "use_webhook", False)
    app = build_app(Bot("1:x"), Dispatcher(), MagicMock(), asyncio.Queue())
    assert settings.tg_webhook_path not in _routes(app)
    assert settings.sentry_webhook_path in _routes(app)

    monkeypatch.setattr(settings, "use_webhook", True)
    app = build_app(Bot("1:x"), Dispatcher(), MagicMock(), asyncio.Queue())
    assert settings.tg_webhook_path in _routes(app)


async def test_start_telegram_webhook_mode(monkeypatch):
    monkeypatch.setattr(settings, "use_webhook", True)
    bot = MagicMock(set_webhook=AsyncMock(), delete_webhook=AsyncMock())
    assert await main.start_telegram(bot, MagicMock()) is None
    kwargs = bot.set_webhook.await_args.kwargs
    assert kwargs["url"] == settings.webhook_base_url + settings.tg_webhook_path
    assert kwargs["secret_token"] == settings.webhook_secret_token
    bot.delete_webhook.assert_not_awaited()


async def test_start_telegram_polling_mode(monkeypatch):
    monkeypatch.setattr(settings, "use_webhook", False)
    bot = MagicMock(set_webhook=AsyncMock(), delete_webhook=AsyncMock())
    started = asyncio.Event()

    async def fake_polling(*bots, **kwargs):
        assert bots == (bot,)
        assert kwargs["handle_signals"] is False and kwargs["close_bot_session"] is False
        assert kwargs["allowed_updates"] == ["message", "callback_query"]
        started.set()

    dp = MagicMock(start_polling=fake_polling)
    task = await main.start_telegram(bot, dp)
    await asyncio.wait_for(task, 1)
    assert started.is_set() and task.get_name() == "polling"
    bot.delete_webhook.assert_awaited_once_with(drop_pending_updates=True)
    bot.set_webhook.assert_not_awaited()
