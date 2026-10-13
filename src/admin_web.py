"""
Read-only web admin page at /admin.

Server-rendered HTML with no JavaScript. Enabled only when ADMIN_TOKEN is
set; the token is accepted as a Bearer token, an X-Admin-Token header or a
?token= query parameter (handy in a browser — links on the page carry it
along, and `Referrer-Policy: no-referrer` keeps it from leaking to Sentry
links).
"""
from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any, Optional
from urllib.parse import urlencode

from aiohttp import web

from .config import settings
from .web import QUEUE_KEY, REPOS_KEY

DELIVERY_STATUSES = ("sent", "failed", "skipped", "digest")
_DELIVERY_LIMIT = 100

_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}

_CSS = """
:root { color-scheme: light dark; --muted: #888; --line: #8884; --bad: #d33; --ok: #2a2; }
body { font: 14px/1.45 system-ui, sans-serif; margin: 0 auto; max-width: 1200px; padding: 16px; }
h1 { font-size: 20px; } h2 { font-size: 16px; margin-top: 28px; }
table { border-collapse: collapse; width: 100%; display: block; overflow-x: auto; }
th, td { text-align: left; padding: 4px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { font-weight: 600; white-space: nowrap; }
code { font-size: 12px; } .muted { color: var(--muted); }
.stats { display: flex; gap: 12px; flex-wrap: wrap; }
.stat { border: 1px solid var(--line); border-radius: 6px; padding: 8px 14px; }
.stat b { display: block; font-size: 20px; }
.failed { color: var(--bad); } .sent { color: var(--ok); }
nav a { margin-right: 10px; }
"""


def _token_from(request: web.Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("X-Admin-Token") or request.query.get("token", "")


def _authorized(request: web.Request) -> bool:
    expected = settings.admin_token
    given = _token_from(request)
    return bool(expected) and hmac.compare_digest(given.encode(), expected.encode())


def _e(value: Any) -> str:
    return escape("" if value is None else str(value))


def _ts(value: Optional[datetime]) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")


def _table(headers: list[str], rows: list[list[str]], empty: str = "none") -> str:
    """`rows` cells must already be HTML-safe."""
    if not rows:
        return f'<p class="muted">{_e(empty)}</p>'
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _link(request: web.Request, **params: str) -> str:
    """Self-link that keeps a query-string token so browser navigation stays logged in."""
    query = {k: v for k, v in params.items() if v}
    if "token" in request.query:
        query["token"] = request.query["token"]
    return "/admin" + ("?" + urlencode(query) if query else "")


def _route_filters(r: dict) -> str:
    bits = []
    if r["min_level"]:
        bits.append(f"level≥{r['min_level']}")
    if r["actions"]:
        bits.append(f"actions={r['actions']}")
    if r["digest_minutes"]:
        bits.append(f"digest {r['digest_minutes']}m")
    if r["thread_id"]:
        bits.append(f"topic {r['thread_id']}")
    muted = r["muted_until"]
    if muted is not None:
        if muted.tzinfo is None:
            muted = muted.replace(tzinfo=timezone.utc)
        if muted > datetime.now(timezone.utc):
            bits.append(f"muted until {_ts(muted)}")
    return _e(", ".join(bits))


async def admin_page(request: web.Request) -> web.Response:
    if not settings.admin_token:
        raise web.HTTPNotFound()
    if not _authorized(request):
        return web.Response(
            status=401, text="Unauthorized", headers={**_SECURITY_HEADERS, "WWW-Authenticate": "Bearer"}
        )

    repos = request.app[REPOS_KEY]
    queue = request.app[QUEUE_KEY]
    status = request.query.get("status", "")
    if status not in DELIVERY_STATUSES:
        status = ""

    now = datetime.now(timezone.utc)
    counts = await repos.deliveries.count_by_status(now - timedelta(hours=24))
    deliveries = await repos.deliveries.recent(limit=_DELIVERY_LIMIT, status=status or None)
    routes = await repos.routes.list_all()
    projects = await repos.projects.list_all()
    envs = await repos.environments.list_all()
    installations = await repos.installations.list_all()

    stats = [("Queue", queue.qsize()), ("Routes", len(routes)), ("Chats", len({r["chat_id"] for r in routes}))]
    stats += [(f"{s} (24h)", counts.get(s, 0)) for s in DELIVERY_STATUSES]
    stats_html = "".join(f'<div class="stat"><b>{_e(v)}</b>{_e(k)}</div>' for k, v in stats)

    route_rows = [
        [f"<code>{_e(r['chat_id'])}</code>", f"<b>{_e(r['project'])}</b>", _e(r["environment"] or "any"),
         _route_filters(r), _e(_ts(r["created_at"])), f"<code>{_e(r['created_by'])}</code>"]
        for r in routes
    ]
    project_rows = [
        [f"<b>{_e(p['slug'])}</b>", _e(p["name"]), _e(p["org"]), _e(p["ref_id"]),
         _e(", ".join(envs.get(p["slug"], [])))]
        for p in projects
    ]
    install_rows = [
        [f"<code>{_e(i['uuid'])}</code>", _e(i["org_slug"]), _e(i["app_slug"]), _e(i["status"]),
         _e(i["secret_label"]), _e(_ts(i["first_seen"])), _e(_ts(i["last_seen"]))]
        for i in installations
    ]
    delivery_rows = [
        [_e(_ts(d["created_at"])), f'<span class="{_e(d["status"])}">{_e(d["status"])}</span>',
         f"<code>{_e(d['chat_id'])}</code>", _e(f"{d['resource']}.{d['action']}"),
         _e(d["project"]) + (f" / {_e(d['environment'])}" if d["environment"] else ""),
         _e(d["title"][:120]), f'<span class="muted">{_e((d["error"] or "")[:200])}</span>']
        for d in deliveries
    ]
    nav = " ".join(
        f'<a href="{_e(_link(request, status=s))}">{"<b>" if s == status else ""}{_e(s or "all")}{"</b>" if s == status else ""}</a>'
        for s in ("", *DELIVERY_STATUSES)
    )

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sentry → Telegram admin</title><style>{_CSS}</style></head>
<body>
<h1>Sentry → Telegram admin</h1>
<p class="muted">Generated {_e(_ts(now))} UTC</p>
<div class="stats">{stats_html}</div>
<h2>Recent deliveries</h2>
<nav>{nav}</nav>
{_table(["Time (UTC)", "Status", "Chat", "Event", "Project", "Title", "Error"], delivery_rows, "no deliveries")}
<h2>Routes ({len(routes)})</h2>
{_table(["Chat", "Project", "Environment", "Settings", "Created (UTC)", "By"], route_rows, "no routes")}
<h2>Projects ({len(projects)})</h2>
{_table(["Slug", "Name", "Org", "Id", "Environments"], project_rows, "no projects seen yet")}
<h2>Installations ({len(installations)})</h2>
{_table(["UUID", "Org", "App", "Status", "Secret", "First seen", "Last seen"], install_rows, "no installations")}
</body></html>"""
    return web.Response(text=html, content_type="text/html", headers=_SECURITY_HEADERS)


def register_admin(app: web.Application) -> None:
    app.router.add_get("/admin", admin_page)
