import asyncio
import hashlib
import hmac
import json
from unittest.mock import MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.config import settings
from src.web import _learn_project, _sentry_webhook, BG_TASKS_KEY, QUEUE_KEY, REPOS_KEY

# Exercise the Sentry handler alone (aiogram's handler needs a live Bot).


def _sign(body: bytes) -> str:
    return hmac.new(settings.sentry_client_secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
async def client(repos):
    app = web.Application()
    app[REPOS_KEY] = repos
    app[QUEUE_KEY] = asyncio.Queue(maxsize=2)
    app[BG_TASKS_KEY] = set()
    app.router.add_post("/sentry", _sentry_webhook)
    async with TestClient(TestServer(app)) as c:
        yield c


async def _post(client, payload, resource="issue", request_id=None, sig=None):
    body = json.dumps(payload).encode()
    headers = {
        "Sentry-Hook-Signature": sig if sig is not None else _sign(body),
        "Sentry-Hook-Resource": resource,
    }
    if request_id:
        headers["Request-ID"] = request_id
    return await client.post("/sentry", data=body, headers=headers)


async def test_bad_signature_rejected(client):
    resp = await _post(client, {"action": "created"}, sig="bad")
    assert resp.status == 401
    assert client.app[QUEUE_KEY].qsize() == 0


async def test_valid_event_enqueued_and_project_learned(client, repos):
    payload = {
        "action": "created",
        "data": {"issue": {"title": "T", "project": {"id": "1", "slug": "backend", "name": "B"}}},
    }
    resp = await _post(client, payload, request_id="req-1")
    assert resp.status == 200
    assert client.app[QUEUE_KEY].qsize() == 1
    await asyncio.gather(*client.app[BG_TASKS_KEY])
    assert await repos.projects.list_all() == [{"slug": "backend", "ref_id": 1, "name": "B", "org": None}]


async def test_duplicate_request_id_skipped(client):
    payload = {"action": "created", "data": {"issue": {"title": "T"}}}
    assert (await _post(client, payload, request_id="dup")).status == 200
    assert (await _post(client, payload, request_id="dup")).status == 200
    assert client.app[QUEUE_KEY].qsize() == 1


async def test_non_object_json_is_400(client):
    assert (await _post(client, [1, 2, 3])).status == 400
    body = b"not json"
    resp = await client.post(
        "/sentry", data=body,
        headers={"Sentry-Hook-Signature": _sign(body), "Sentry-Hook-Resource": "issue"},
    )
    assert resp.status == 400


async def test_full_queue_returns_503_without_marking_seen(client, repos):
    payload = {"action": "created", "data": {"issue": {"title": "T"}}}
    await _post(client, payload, request_id="a")
    await _post(client, payload, request_id="b")
    resp = await _post(client, payload, request_id="c")
    assert resp.status == 503
    assert not await repos.seen.exists("c")  # Sentry's retry must not be deduped away
