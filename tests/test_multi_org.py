import hashlib
import hmac
import json

from src.config import Settings, settings
from src.delivery import _resolve_chats
from src.sentry.parser import ParsedEvent, parse
from src.sentry.signature import verify_any
from tests.test_web import _post, client  # noqa: F401 — reuse fixture


def test_secrets_parsing():
    assert settings.all_sentry_secrets == {"default": "sentry_secret", "acme": "acme_secret"}
    s = Settings(sentry_client_secret="", sentry_client_secrets='{"a": "1", "b": "2"}')
    assert s.all_sentry_secrets == {"a": "1", "b": "2"} and s.multi_org


def test_verify_any_returns_label():
    body = b"{}"
    sig = hmac.new(b"acme_secret", body, hashlib.sha256).hexdigest()
    assert verify_any(body, sig, settings.all_sentry_secrets) == "acme"
    assert verify_any(body, "nope", settings.all_sentry_secrets) is None


def test_installation_event_carries_org():
    ev = parse({"action": "created", "data": {"installation": {
        "uuid": "u-1", "organization": {"slug": "acme"}, "app": {"slug": "tg-bot"}}}}, "installation")
    assert ev.org == "acme" and ev.installation_uuid == "u-1"


async def test_org_learned_from_installation_then_applied(client, repos):
    install = {"action": "created", "data": {"installation": {
        "uuid": "u-1", "organization": {"slug": "acme"}, "app": {"slug": "tg-bot"}}},
        "installation": {"uuid": "u-1"}}
    assert (await _post(client, install, resource="installation")).status == 200
    import asyncio
    from src.web import BG_TASKS_KEY, QUEUE_KEY
    await asyncio.gather(*client.app[BG_TASKS_KEY])
    assert await repos.installations.org_for("u-1") == "acme"

    issue = {"action": "created", "installation": {"uuid": "u-1"},
             "data": {"issue": {"title": "T", "project": {"id": "1", "slug": "backend"}}}}
    assert (await _post(client, issue, request_id="x")).status == 200
    await asyncio.gather(*client.app[BG_TASKS_KEY])
    q = client.app[QUEUE_KEY]
    q.get_nowait()  # the installation event
    ev = q.get_nowait()
    assert ev.org == "acme"
    [proj] = await repos.projects.list_all()
    assert proj["org"] == "acme"


async def test_secret_label_used_as_org_and_org_routes_win(client, repos):
    body = json.dumps({"action": "created", "data": {"issue": {"title": "T", "project": {"slug": "backend"}}}}).encode()
    sig = hmac.new(b"acme_secret", body, hashlib.sha256).hexdigest()
    resp = await client.post("/sentry", data=body, headers={"Sentry-Hook-Signature": sig, "Sentry-Hook-Resource": "issue"})
    assert resp.status == 200
    from src.web import QUEUE_KEY
    ev = client.app[QUEUE_KEY].get_nowait()
    assert ev.org == "acme"

    await repos.routes.add("backend", None, 1)
    await repos.routes.add("acme/backend", None, 2)
    assert await _resolve_chats(repos, ev) == [2]
    ev.org = None
    assert await _resolve_chats(repos, ev) == [1]
