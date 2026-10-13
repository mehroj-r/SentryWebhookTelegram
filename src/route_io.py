"""
Export / import of a chat's routes as a JSON document.

Format (version 1):

    {
      "version": 1,
      "chat_id": -100500,
      "routes": [
        {"project": "backend", "environment": "production",
         "min_level": "error", "actions": "created,resolved",
         "digest_minutes": 60, "thread_id": 7}
      ]
    }

Mutes are deliberately not exported: they are temporary by nature. `chat_id`
lets the importer tell whether `thread_id` values still make sense (forum
topic ids are per-chat).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .filters import normalize_level, parse_actions

FORMAT_VERSION = 1
MAX_ROUTES = 500
MAX_BYTES = 256 * 1024

# Sentry slugs: lowercase letters, digits, '-' and '_' (we're lenient on case).
# Project key: "slug", "org/slug" (multi-org) or a wildcard pattern ("backend-*", "*").
SLUG_RE = re.compile(r"^(?:[A-Za-z0-9_\-.*]{1,64}/)?[A-Za-z0-9_\-.*]{1,64}$")
_ACTION_RE = re.compile(r"^[a-z_]+$")

_EXPORTED_FIELDS = ("project", "environment", "min_level", "actions", "digest_minutes", "thread_id")


def export_routes(chat_id: int, routes: list[dict]) -> str:
    doc = {
        "version": FORMAT_VERSION,
        "chat_id": chat_id,
        "routes": [{k: r.get(k) for k in _EXPORTED_FIELDS} for r in routes],
    }
    return json.dumps(doc, indent=2, ensure_ascii=False)


@dataclass
class ImportResult:
    routes: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    source_chat_id: Optional[int] = None


def parse_import(text: str) -> ImportResult:
    """
    Validate an export document. Either every route is valid (`errors` empty)
    or nothing should be imported — partial imports are confusing to undo.
    Accepts a bare list of routes as well as the full document.
    """
    result = ImportResult()
    if len(text.encode()) > MAX_BYTES:
        result.errors.append(f"document is larger than {MAX_BYTES // 1024} KB")
        return result
    try:
        doc: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        result.errors.append(f"invalid JSON: {exc.msg} (line {exc.lineno})")
        return result

    if isinstance(doc, dict):
        version = doc.get("version", FORMAT_VERSION)
        if version != FORMAT_VERSION:
            result.errors.append(f"unsupported version {version!r}")
            return result
        chat_id = doc.get("chat_id")
        if isinstance(chat_id, int) and not isinstance(chat_id, bool):
            result.source_chat_id = chat_id
        items = doc.get("routes")
    else:
        items = doc
    if not isinstance(items, list):
        result.errors.append("expected a 'routes' list")
        return result
    if len(items) > MAX_ROUTES:
        result.errors.append(f"too many routes ({len(items)} > {MAX_ROUTES})")
        return result

    seen: set[tuple[str, Optional[str]]] = set()
    for i, item in enumerate(items, start=1):
        route, error = _validate_route(item)
        if error:
            result.errors.append(f"route #{i}: {error}")
            continue
        key = (route["project"], route["environment"])
        if key in seen:
            result.errors.append(f"route #{i}: duplicate {key[0]} / {key[1] or 'any environment'}")
            continue
        seen.add(key)
        result.routes.append(route)
    return result


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _validate_route(item: Any) -> tuple[dict, Optional[str]]:
    if not isinstance(item, dict):
        return {}, "not an object"
    unknown = set(item) - set(_EXPORTED_FIELDS) - {"muted_until"}
    if unknown:
        return {}, f"unknown field(s) {', '.join(sorted(unknown))}"

    project = item.get("project")
    if not isinstance(project, str) or not SLUG_RE.match(project):
        return {}, "invalid or missing project"

    environment = item.get("environment")
    if environment is not None and (
        not isinstance(environment, str) or not environment or len(environment) > 64
    ):
        return {}, "invalid environment"

    min_level = item.get("min_level")
    if min_level is not None:
        min_level = normalize_level(min_level) if isinstance(min_level, str) else None
        if min_level is None:
            return {}, "invalid min_level"

    actions = item.get("actions")
    if actions is not None:
        if isinstance(actions, list):
            actions = ",".join(a for a in actions if isinstance(a, str))
        parsed = parse_actions(actions) if isinstance(actions, str) else None
        if not parsed or any(not _ACTION_RE.match(a) for a in parsed):
            return {}, "invalid actions"
        actions = ",".join(parsed)

    digest = item.get("digest_minutes")
    if digest is not None and (not _is_int(digest) or not 1 <= digest <= 24 * 60):
        return {}, "digest_minutes must be 1–1440 or null"

    thread_id = item.get("thread_id")
    if thread_id is not None and (not _is_int(thread_id) or thread_id <= 0):
        return {}, "invalid thread_id"

    return {
        "project": project,
        "environment": environment,
        "min_level": min_level,
        "actions": actions,
        "digest_minutes": digest,
        "thread_id": thread_id,
    }, None
