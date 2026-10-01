from __future__ import annotations

import asyncio
import logging
import signal
from datetime import timedelta

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from src.config import settings
from src.db import Database, Repositories
from src.bot.handlers import admin_router, public_router
from src.delivery import delivery_worker
from src.web import build_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

_PURGE_INTERVAL_S = 3600


async def _purge_seen_requests(repos: Repositories) -> None:
    """Periodically drop old Request-ID dedup rows so the table doesn't grow forever."""
    max_age = timedelta(days=settings.seen_request_ttl_days)
    while True:
        try:
            removed = await repos.seen.purge_older_than(max_age)
            if removed:
                log.info("Purged %d old seen_requests rows", removed)
        except Exception:
            log.exception("seen_requests purge failed")
        await asyncio.sleep(_PURGE_INTERVAL_S)


async def main() -> None:
    # ── DB: infrastructure core ───────────────────────────────────────────────
    db = Database(settings.db_path)
    await db.connect()
    repos = Repositories(db.sessionmaker)

    # ── Telegram bot + dispatcher ─────────────────────────────────────────────
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode="HTML", link_preview_is_disabled=True),
    )
    dp = Dispatcher()
    dp.include_router(public_router)
    dp.include_router(admin_router)
    dp["repos"] = repos  # handlers declare `repos: Repositories`

    queue: asyncio.Queue = asyncio.Queue(maxsize=settings.queue_max_size)
    runner: web.AppRunner | None = None
    worker_task: asyncio.Task | None = None
    purge_task: asyncio.Task | None = None

    try:
        # ── Telegram webhook registration ─────────────────────────────────────
        tg_webhook_url = settings.webhook_base_url + settings.tg_webhook_path
        await bot.set_webhook(
            url=tg_webhook_url,
            secret_token=settings.webhook_secret_token,
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query"],
        )
        log.info("Telegram webhook registered: %s", tg_webhook_url)

        # ── background tasks ──────────────────────────────────────────────────
        worker_task = asyncio.create_task(delivery_worker(queue, bot, repos), name="delivery")
        purge_task = asyncio.create_task(_purge_seen_requests(repos), name="purge")

        # ── aiohttp server ────────────────────────────────────────────────────
        app = build_app(bot, dp, repos, queue)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, settings.host, settings.port)
        await site.start()
        log.info(
            "Listening on %s:%d  |  Sentry: %s  |  Telegram: %s",
            settings.host, settings.port, settings.sentry_webhook_path, settings.tg_webhook_path,
        )

        # ── run until interrupted (or until the worker dies) ──────────────────
        stop_event = asyncio.Event()

        def _signal_handler() -> None:
            log.info("Shutdown signal received")
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _signal_handler)

        stop_task = asyncio.create_task(stop_event.wait(), name="stop")
        done, _ = await asyncio.wait({stop_task, worker_task}, return_when=asyncio.FIRST_COMPLETED)
        if worker_task in done:
            exc = worker_task.exception() if not worker_task.cancelled() else None
            log.critical("Delivery worker exited unexpectedly: %r — shutting down", exc)
        stop_task.cancel()

    finally:
        # ── graceful shutdown ─────────────────────────────────────────────────
        log.info("Shutting down…")

        # 1. Stop accepting webhooks first, so nothing is enqueued after the sentinel.
        if runner is not None:
            await runner.cleanup()

        # 2. Let the worker drain what is already queued.
        if worker_task is not None and not worker_task.done():
            await queue.put(None)
            try:
                await asyncio.wait_for(worker_task, timeout=15)
            except asyncio.TimeoutError:
                log.warning("Delivery worker did not stop in time; cancelled")
            except Exception:
                log.exception("Delivery worker failed during shutdown")

        if purge_task is not None:
            purge_task.cancel()
            await asyncio.gather(purge_task, return_exceptions=True)

        await db.close()
        await bot.session.close()
        log.info("Bye.")


if __name__ == "__main__":
    asyncio.run(main())
