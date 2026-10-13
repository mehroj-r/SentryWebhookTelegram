from __future__ import annotations

import asyncio
import hmac
import json
import time
import logging
from typing import Any

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from . import metrics
from .config import settings
from .db import Repositories
from .sentry.parser import ParsedEvent, parse as parse_sentry_event
from .sentry.signature import verify_any

log = logging.getLogger(__name__)

# Typed app keys (aiohttp ≥3.9 warns on plain string keys).
REPOS_KEY: web.AppKey[Repositories] = web.AppKey("repos", Repositories)
BOT_KEY: web.AppKey[Bot] = web.AppKey("bot", Bot)
QUEUE_KEY: web.AppKey["asyncio.Queue[ParsedEvent | None]"] = web.AppKey("queue", asyncio.Queue)
BG_TASKS_KEY: web.AppKey[set["asyncio.Task[Any]"]] = web.AppKey("bg_tasks", set)


def _spawn(app: web.Application, coro) -> None:  # type: ignore[no-untyped-def]
    """
    Fire-and-forget with a strong reference. asyncio only keeps weak refs to
    tasks, so an un-referenced task can be garbage-collected mid-flight.
    """
    task = asyncio.create_task(coro)
    tasks = app[BG_TASKS_KEY]
    tasks.add(task)
    task.add_done_callback(tasks.discard)


async def _sentry_webhook(request: web.Request) -> web.Response:
    """
    Receive a Sentry webhook, verify its signature, and enqueue the parsed
    event for async delivery. Returns 200 immediately (fast-ack pattern).
    """
    app = request.app
    repos = app[REPOS_KEY]
    queue = app[QUEUE_KEY]

    # 1. Read raw bytes FIRST — required for correct HMAC verification
    raw_body = await request.read()

    # 2. Verify HMAC-SHA256 signature
    sig = request.headers.get("Sentry-Hook-Signature", "")
    secret_label = verify_any(raw_body, sig, settings.all_sentry_secrets)
    if secret_label is None:
        log.warning("Rejected Sentry request with invalid signature from %s", request.remote)
        metrics.webhooks_rejected.inc(reason="signature")
        return web.Response(status=401, text="Invalid signature")

    # 2b. Replay window. Sentry signs only the body, so a determined attacker
    #     can forge this header; it still stops verbatim replays of captured
    #     requests, and Request-ID dedup below catches exact duplicates.
    if _is_stale(request.headers.get("Sentry-Hook-Timestamp")):
        log.warning("Rejected stale/invalid Sentry-Hook-Timestamp from %s", request.remote)
        metrics.webhooks_rejected.inc(reason="stale")
        return web.Response(status=401, text="Stale request")

    # 3. Decode JSON
    resource = request.headers.get("Sentry-Hook-Resource", "")
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        log.warning("Invalid JSON from Sentry (resource=%s)", resource)
        metrics.webhooks_rejected.inc(reason="json")
        return web.Response(status=400, text="Invalid JSON")
    if not isinstance(payload, dict):
        log.warning("Unexpected JSON payload type %s (resource=%s)", type(payload).__name__, resource)
        metrics.webhooks_rejected.inc(reason="json")
        return web.Response(status=400, text="Invalid JSON")

    # 4. Back-pressure before we mark the hook as seen: a full queue means
    #    Telegram is unreachable; tell Sentry to retry later instead of
    #    swallowing the event.
    if queue.full():
        log.error("Delivery queue full (%d); asking Sentry to retry", queue.qsize())
        metrics.webhooks_rejected.inc(reason="busy")
        return web.Response(status=503, text="Busy, retry later", headers={"Retry-After": "60"})

    # 5. Dedup by Request-ID (atomic insert; concurrent duplicates lose the race)
    request_id = request.headers.get("Request-ID", "")
    if request_id:
        try:
            is_new = await repos.seen.add_if_new(request_id)
        except Exception:
            log.exception("Dedup store failed; delivering anyway")
            is_new = True
        if not is_new:
            log.debug("Duplicate Request-ID=%s, skipping", request_id)
            metrics.webhooks_deduplicated.inc()
            return web.Response(status=200, text="ok")

    # 6. Parse — never let parse errors block the 200 response
    try:
        event: ParsedEvent = parse_sentry_event(payload, resource)
    except Exception:
        log.exception("Failed to parse Sentry event resource=%s", resource)
        return web.Response(status=200, text="ok")

    # 7. Attribute the event to an organisation (multi-org deployments)
    await _attach_org(repos, event, secret_label)

    # 8. Enqueue — this is the fast-ack point
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        log.error("Delivery queue full; asking Sentry to retry")
        metrics.webhooks_rejected.inc(reason="busy")
        return web.Response(status=503, text="Busy, retry later", headers={"Retry-After": "60"})

    metrics.webhooks_received.inc(resource=resource or "unknown")

    # 9. Best-effort metadata learning in the background
    _spawn(app, _learn_project(repos, event, payload))

    return web.Response(status=200, text="ok")


def _is_stale(header: str | None, now: float | None = None) -> bool:
    """True when the timestamp is unparseable or outside REPLAY_WINDOW_SECONDS. Missing → not stale."""
    window = settings.replay_window_seconds
    if window <= 0 or not header:
        return False
    try:
        ts = float(header)
    except ValueError:
        return True
    if ts > 1e11:  # milliseconds
        ts /= 1000
    return abs((now if now is not None else time.time()) - ts) > window


async def _attach_org(repos: Repositories, event: ParsedEvent, secret_label: str) -> None:
    """
    Fill event.org: the installation's organisation slug if we learned it from
    an `installation.created` hook, else the label of the secret that matched
    (meaningful when several secrets are configured).
    """
    if event.org:
        return
    if event.installation_uuid:
        try:
            event.org = await repos.installations.org_for(event.installation_uuid)
        except Exception:
            log.debug("Installation lookup failed", exc_info=True)
    if not event.org and secret_label != "default":
        event.org = secret_label


async def _learn_project(
    repos: Repositories, event: ParsedEvent, payload: dict[str, Any]
) -> None:
    """
    Best-effort: persist project + environment metadata so the routing UI
    can list them without the user needing to type slugs manually.
    """
    try:
        if event.installation_uuid:
            await repos.installations.upsert(
                event.installation_uuid,
                org_slug=event.org if event.resource == "installation" else None,
                app_slug=event.extra.get("app_slug") if event.resource == "installation" else None,
                status=event.extra.get("status") if event.resource == "installation" else None,
            )
        slug = event.project_slug
        if not slug:
            return
        data = payload.get("data")
        data = data if isinstance(data, dict) else {}
        name: str | None = None
        for key in ("issue", "error", "event"):
            obj = data.get(key)
            if isinstance(obj, dict):
                proj = obj.get("project")
                if isinstance(proj, dict):
                    name = proj.get("name") or proj.get("slug")
                    break
        await repos.projects.upsert(slug, event.project_ref_id, name, org=event.org)
        if event.environment:
            await repos.environments.register(slug, event.environment)
    except Exception:
        log.debug("Could not persist project metadata", exc_info=True)


async def _health(request: web.Request) -> web.Response:
    queue = request.app[QUEUE_KEY]
    return web.json_response({"status": "ok", "queue_size": queue.qsize()})


async def _metrics(request: web.Request) -> web.Response:
    token = settings.metrics_token
    if token:
        given = request.headers.get("Authorization", "")
        if not hmac.compare_digest(given.encode(), f"Bearer {token}".encode()):
            return web.Response(status=401, text="Unauthorized", headers={"WWW-Authenticate": "Bearer"})
    queue = request.app[QUEUE_KEY]
    return web.Response(
        text=metrics.render(queue.qsize),
        headers={"Content-Type": "text/plain; version=0.0.4; charset=utf-8"},
    )


async def _wait_background_tasks(app: web.Application) -> None:
    tasks = list(app[BG_TASKS_KEY])
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def build_app(
    bot: Bot, dp: Dispatcher, repos: Repositories, queue: "asyncio.Queue[ParsedEvent | None]"
) -> web.Application:
    """Build the aiohttp Application with Sentry + Telegram webhook routes."""
    app = web.Application(client_max_size=settings.max_body_bytes)
    app[REPOS_KEY] = repos
    app[BOT_KEY] = bot
    app[QUEUE_KEY] = queue
    app[BG_TASKS_KEY] = set()

    app.router.add_get("/health", _health)
    app.router.add_get("/metrics", _metrics)

    from .admin_web import register_admin  # imports this module's app keys

    register_admin(app)

    # Sentry receiver
    app.router.add_post(settings.sentry_webhook_path, _sentry_webhook)

    # Telegram webhook (aiogram). In polling mode main.py runs the dispatcher
    # itself, including its startup/shutdown hooks.
    if settings.use_webhook:
        SimpleRequestHandler(
            dispatcher=dp,
            bot=bot,
            secret_token=settings.webhook_secret_token,
        ).register(app, path=settings.tg_webhook_path)
        setup_application(app, dp, bot=bot)
    app.on_shutdown.append(_wait_background_tasks)

    return app
