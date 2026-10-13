import asyncio
import hashlib
import hmac
import json
import time

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src import metrics
from src.config import settings
from src.web import BG_TASKS_KEY, QUEUE_KEY, REPOS_KEY, _is_stale, _sentry_webhook


def test_is_stale(monkeypatch):
    monkeypatch.setattr(settings, "replay_window_seconds", 300)
    now = 1_800_000_000
    assert not _is_stale(None, now) and not _is_stale("", now)
    assert not _is_stale(str(now - 299), now) and not _is_stale(f"{now - 10}.5", now)
    assert _is_stale(str(now - 301), now) and _is_stale(str(now + 301), now)  # clock skew both ways
    assert not _is_stale(str((now - 5) * 1000), now)  # milliseconds accepted
    assert _is_stale("yesterday", now)
    monkeypatch.setattr(settings, "replay_window_seconds", 0)
    assert not _is_stale(str(now - 10_000), now)


@pytest.fixture
async def client(repos, monkeypatch):
    monkeypatch.setattr(settings, "replay_window_seconds", 300)
    metrics.reset()
    app = web.Application()
    app[REPOS_KEY] = repos
    app[QUEUE_KEY] = asyncio.Queue()
    app[BG_TASKS_KEY] = set()
    app.router.add_post("/sentry", _sentry_webhook)
    async with TestClient(TestServer(app)) as c:
        yield c
    metrics.reset()


async def _post(client, ts=None, sig=None):
    body = json.dumps({"action": "created", "data": {"issue": {"title": "T"}}}).encode()
    headers = {
        "Sentry-Hook-Signature": sig or hmac.new(settings.sentry_client_secret.encode(), body, hashlib.sha256).hexdigest(),
        "Sentry-Hook-Resource": "issue",
    }
    if ts is not None:
        headers["Sentry-Hook-Timestamp"] = str(ts)
    return await client.post("/sentry", data=body, headers=headers)


async def test_stale_rejected_fresh_accepted(client, repos):
    assert (await _post(client, ts=int(time.time()) - 3600)).status == 401
    assert metrics.webhooks_rejected.value(reason="stale") == 1
    assert client.app[QUEUE_KEY].qsize() == 0
    assert (await _post(client, ts=int(time.time()))).status == 200
    assert (await _post(client)).status == 200  # header absent → accepted
    assert client.app[QUEUE_KEY].qsize() == 2


async def test_signature_checked_first(client):
    resp = await _post(client, ts=0, sig="bad")
    assert resp.status == 401 and await resp.text() == "Invalid signature"
    assert metrics.webhooks_rejected.value(reason="stale") == 0
