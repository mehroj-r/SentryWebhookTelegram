import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.admin_web import register_admin
from src.config import settings
from src.web import BG_TASKS_KEY, QUEUE_KEY, REPOS_KEY

TOKEN = "s3cret-admin-token"


@pytest.fixture
async def client(repos, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", TOKEN)
    app = web.Application()
    app[REPOS_KEY] = repos
    app[QUEUE_KEY] = asyncio.Queue()
    app[BG_TASKS_KEY] = set()
    register_admin(app)
    async with TestClient(TestServer(app)) as c:
        yield c


async def _record(repos, title, status, error=None):
    await repos.deliveries.record(
        chat_id=-100, resource="issue", action="created", project="backend", environment="prod",
        issue_id="1", title=title, status=status, error=error,
    )


async def test_disabled_without_token(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "")
    resp = await client.get("/admin", headers={"Authorization": "Bearer "})
    assert resp.status == 404


@pytest.mark.parametrize("kwargs", [
    {},
    {"params": {"token": "wrong"}},
    {"headers": {"Authorization": "Bearer wrong"}},
])
async def test_rejects_missing_or_wrong_token(client, kwargs):
    resp = await client.get("/admin", **kwargs)
    assert resp.status == 401
    assert resp.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("kwargs", [
    {"params": {"token": TOKEN}},
    {"headers": {"Authorization": f"Bearer {TOKEN}"}},
    {"headers": {"X-Admin-Token": TOKEN}},
])
async def test_accepts_token_forms(client, kwargs):
    resp = await client.get("/admin", **kwargs)
    assert resp.status == 200
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'none'" in resp.headers["Content-Security-Policy"]


async def test_page_lists_everything_escaped(client, repos):
    await repos.projects.upsert("backend", 5, "<Backend>", org="acme")
    await repos.environments.register("backend", "prod")
    await repos.installations.upsert("uuid-1", org_slug="acme", status="installed")
    await repos.routes.add("backend", "prod", -100, created_by=1, thread_id=3)
    await repos.routes.set_filters(-100, "backend", min_level="error")
    await _record(repos, "<script>x</script>", "sent")
    await _record(repos, "Nope", "failed", "forbidden: <kicked>")
    client.app[QUEUE_KEY].put_nowait(None)

    resp = await client.get("/admin", params={"token": TOKEN})
    html = await resp.text()
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "&lt;Backend&gt;" in html and "uuid-1" in html
    assert "level≥error, topic 3" in html
    assert "forbidden: &lt;kicked&gt;" in html
    assert '<div class="stat"><b>1</b>Queue</div>' in html
    assert '<div class="stat"><b>1</b>failed (24h)</div>' in html
    # filter links keep the query token
    assert f"/admin?status=failed&amp;token={TOKEN}" in html


async def test_status_filter(client, repos):
    await _record(repos, "Delivered one", "sent")
    await _record(repos, "Broken one", "failed", "x")
    html = await (await client.get("/admin", params={"token": TOKEN, "status": "failed"})).text()
    assert "Broken one" in html and "Delivered one" not in html
    html = await (await client.get("/admin", params={"token": TOKEN, "status": "bogus"})).text()
    assert "Broken one" in html and "Delivered one" in html
