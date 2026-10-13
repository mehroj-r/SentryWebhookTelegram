import asyncio
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src import metrics
from src.config import settings
from src.delivery import send_event
from src.sentry.parser import ParsedEvent
from src.web import BG_TASKS_KEY, QUEUE_KEY, REPOS_KEY, _metrics, _sentry_webhook


@pytest.fixture(autouse=True)
def _fresh_metrics():
    metrics.reset()
    yield
    metrics.reset()


@pytest.fixture
async def client(repos):
    app = web.Application()
    app[REPOS_KEY] = repos
    app[QUEUE_KEY] = asyncio.Queue(maxsize=2)
    app[BG_TASKS_KEY] = set()
    app.router.add_post("/sentry", _sentry_webhook)
    app.router.add_get("/metrics", _metrics)
    async with TestClient(TestServer(app)) as c:
        yield c


async def _post(client, body: bytes, request_id=None, sig=None):
    headers = {
        "Sentry-Hook-Signature": sig or hmac.new(settings.sentry_client_secret.encode(), body, hashlib.sha256).hexdigest(),
        "Sentry-Hook-Resource": "issue",
    }
    if request_id:
        headers["Request-ID"] = request_id
    return await client.post("/sentry", data=body, headers=headers)


def test_render_format():
    metrics.webhooks_received.inc(resource='we"ird')
    metrics.webhooks_received.inc(resource='we"ird')
    text = metrics.render(lambda: 3)
    assert '# TYPE sentry_telegram_webhooks_received_total counter' in text
    assert 'sentry_telegram_webhooks_received_total{resource="we\\"ird"} 2' in text
    assert "sentry_telegram_webhooks_deduplicated_total 0" in text  # unlabelled counters always present
    assert "sentry_telegram_queue_size 3" in text
    assert text.endswith("\n")


async def test_webhook_counters(client):
    body = json.dumps({"action": "created", "data": {"issue": {"title": "T"}}}).encode()
    await _post(client, body, request_id="r1")
    await _post(client, body, request_id="r1")  # duplicate
    await _post(client, body, sig="bad")
    await _post(client, b"not json")
    await _post(client, body, request_id="r2")
    await _post(client, body, request_id="r3")  # queue (maxsize 2) is full → busy
    assert metrics.webhooks_received.value(resource="issue") == 2
    assert metrics.webhooks_deduplicated.value() == 1
    assert metrics.webhooks_rejected.value(reason="signature") == 1
    assert metrics.webhooks_rejected.value(reason="json") == 1
    assert metrics.webhooks_rejected.value(reason="busy") == 1

    resp = await client.get("/metrics")
    assert resp.status == 200
    assert resp.headers["Content-Type"].startswith("text/plain; version=0.0.4")
    text = await resp.text()
    assert 'sentry_telegram_webhooks_rejected_total{reason="busy"} 1' in text
    assert "sentry_telegram_queue_size 2" in text


async def test_delivery_counters(repos):
    await repos.routes.add("p", None, 10)
    await repos.routes.add("p", None, 20)
    await repos.routes.set_filters(20, None, min_level="fatal")
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    event = ParsedEvent(resource="issue", action="created", project_slug="p", project_ref_id=None,
                        environment=None, title="t", web_url=None, extra={"level": "error"})
    await send_event(bot, repos, event)
    assert metrics.deliveries.value(status="sent") == 1
    assert metrics.deliveries.value(status="skipped") == 1


async def test_metrics_token(client, monkeypatch):
    monkeypatch.setattr(settings, "metrics_token", "scrape-me")
    assert (await client.get("/metrics")).status == 401
    assert (await client.get("/metrics", headers={"Authorization": "Bearer nope"})).status == 401
    assert (await client.get("/metrics", headers={"Authorization": "Bearer scrape-me"})).status == 200
