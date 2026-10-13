import json

import pytest
from aiogram.types import Chat

from src.route_io import MAX_BYTES, export_routes, parse_import
from tests.bot_harness import GROUP, OTHER, Harness

OTHER_CHAT = Chat(id=-100777, type="supergroup", title="Other")


@pytest.fixture
def h(repos):
    return Harness(repos)


# ── pure parsing ───────────────────────────────────────────────────────────────


def test_export_round_trip():
    routes = [{
        "id": 3, "project": "backend", "environment": "prod", "chat_id": 5, "min_level": "error",
        "actions": "created", "digest_minutes": 30, "thread_id": 7, "muted_until": None,
    }]
    result = parse_import(export_routes(5, routes))
    assert result.errors == []
    assert result.source_chat_id == 5
    assert result.routes == [{
        "project": "backend", "environment": "prod", "min_level": "error",
        "actions": "created", "digest_minutes": 30, "thread_id": 7,
    }]


def test_parse_accepts_bare_list_and_normalises():
    result = parse_import(json.dumps([
        {"project": "acme/web-*", "min_level": "CRITICAL", "actions": ["Created", "resolved"]},
    ]))
    assert result.errors == []
    [r] = result.routes
    assert r["min_level"] == "fatal" and r["actions"] == "created,resolved"
    assert r["environment"] is None and result.source_chat_id is None


@pytest.mark.parametrize("doc, needle", [
    ("{nope", "invalid JSON"),
    ('{"version": 2, "routes": []}', "unsupported version"),
    ('{"routes": {}}', "'routes' list"),
    ('[{"project": "<b>x</b>"}]', "invalid or missing project"),
    ('[{"project": "a", "environment": ""}]', "invalid environment"),
    ('[{"project": "a", "min_level": "loud"}]', "invalid min_level"),
    ('[{"project": "a", "actions": "a;b"}]', "invalid actions"),
    ('[{"project": "a", "digest_minutes": 0}]', "digest_minutes"),
    ('[{"project": "a", "digest_minutes": true}]', "digest_minutes"),
    ('[{"project": "a", "thread_id": -1}]', "invalid thread_id"),
    ('[{"project": "a", "chat_id": 1}]', "unknown field"),
    ('[{"project": "a"}, {"project": "a"}]', "duplicate"),
    ('["a"]', "not an object"),
])
def test_parse_rejects(doc, needle):
    result = parse_import(doc)
    assert any(needle in e for e in result.errors), result.errors


def test_parse_rejects_oversized():
    assert parse_import(" " * (MAX_BYTES + 1)).errors


# ── handlers ───────────────────────────────────────────────────────────────────


async def test_export_sends_json_document(h, repos):
    await h.command("/export")
    assert "No routing rules" in h.session.last_text

    await h.command("/add_route backend prod")
    await h.command("/filter backend level=error")
    await h.command("/export", user=OTHER)  # read-only, public
    [doc] = h.session.documents
    payload = json.loads(doc.document.data)
    assert payload["chat_id"] == GROUP.id
    assert payload["routes"][0]["project"] == "backend"
    assert payload["routes"][0]["min_level"] == "error"


async def test_import_document_into_other_chat_merges(h, repos):
    await repos.routes.add("backend", "prod", OTHER_CHAT.id)
    doc = export_routes(GROUP.id, [
        {"project": "backend", "environment": "prod", "min_level": "error", "thread_id": 9},
        {"project": "web-*", "environment": None, "digest_minutes": 60, "thread_id": 9},
    ]).encode()
    await h.command("/import", chat=OTHER_CHAT, document=doc)
    assert "2 route(s): 1 added, 1 updated" in h.session.last_text

    routes = {r["project"]: r for r in await repos.routes.list_for_chat(OTHER_CHAT.id)}
    assert routes["backend"]["min_level"] == "error"
    assert routes["web-*"]["digest_minutes"] == 60
    # Topic ids from another chat are dropped.
    assert routes["backend"]["thread_id"] is None and routes["web-*"]["thread_id"] is None


async def test_import_same_chat_keeps_topic(h, repos):
    doc = export_routes(GROUP.id, [{"project": "api", "environment": None, "thread_id": 9}])
    await h.command("/import " + doc)
    [r] = await repos.routes.list_for_chat(GROUP.id)
    assert r["thread_id"] == 9


async def test_import_by_reply_to_document_and_text(h, repos):
    file = h.upload(b'[{"project": "a"}]')
    await h.command("/import", reply_to=h.message(document=file))
    assert "1 added" in h.session.last_text

    await h.command("/import", reply_to=h.message(text='[{"project": "b"}]'))
    assert "1 added" in h.session.last_text
    assert [r["project"] for r in await repos.routes.list_for_chat(GROUP.id)] == ["a", "b"]


async def test_import_is_all_or_nothing_and_escapes_errors(h, repos):
    await h.command('/import [{"project": "ok"}, {"project": "x", "environment": "<i>"}, {"project": "x", "environment": "<i>"}]')
    assert "Nothing imported" in h.session.last_text
    assert "duplicate x / &lt;i&gt;" in h.session.last_text
    assert await repos.routes.list_for_chat(GROUP.id) == []


async def test_import_usage_size_limit_and_admin_only(h, repos):
    await h.command("/import")
    assert "Usage" in h.session.last_text

    big = h.upload(b"[]", file_size=MAX_BYTES + 1)
    await h.command("/import", reply_to=h.message(document=big))
    assert "larger than" in h.session.last_text

    await h.command('/import [{"project": "a"}]', user=OTHER)
    assert "not allowed" in h.session.last_text
    assert await repos.routes.list_for_chat(GROUP.id) == []
