# Progress

Roadmap for the Sentry → Telegram bot. One feature per commit, each with tests.
Run `.venv/bin/python -m pytest` before and after every change (142 tests at last update).

## Done

| # | Feature | Commit | Notes |
|---|---------|--------|-------|
| 0 | Review fixes (security, routing, reliability) + test suite | `2ad3f1c` | |
| 1 | Alembic migrations, auto-applied on startup | `de05ad3` | `migrations/`, `Database.connect()` runs `upgrade head`; in-memory DB uses `create_all` |
| 2 | Delivery log + `/last` | `894183e` | `deliveries` table, `DeliveryRepository`, worker records sent/failed/skipped/digest |
| 3 | Message threading + status stamping | `60f9f36` | Replies to first post about an issue; `status_footer()` edits original |
| 4 | Noise control: `/filter`, `/mute`, `/unmute` | `7cb0311` | `src/filters.py` (`skip_reason`), route cols `min_level/actions/muted_until` |
| 5a | Burst collapse | `f180573` | `src/burst.py`, `BURST_WINDOW_SECONDS`, summary threaded under issue |
| 5b | Digest routes `/digest` | `ac4de86` | `digest_items` table, `flush_digests()`, instant beats digest |
| 6 | Rich error context | `71c3482` | `_event_context()` in parser; expandable blockquote in formatter |
| 7 | Release/deploy notifications | `3f41c98` | `release`/`deploy` resources; payload shape documented in `_parse_release` |
| 8 | Multi-org | `00ab523` | `SENTRY_CLIENT_SECRETS`, `installations` table, `org/slug` routes, `[org]` prefix |
| 9 | Wildcard routes | `f3b41b9` | fnmatch on `routes.project` containing `*`; exact beats pattern |
| 10 | Per-chat settings | `82a2579` | `chat_settings` table, `/settings` `/tz` `/quiet`; topic routing via `thread_id` |
| 11 | Export / import routes | `b6d9ff8` | `src/route_io.py` (format v1, all-or-nothing validation), `RouteRepository.import_routes` merges; `/export` public, `/import` admin; thread ids dropped when importing into another chat |
| 12 | Audit log, `/routes verbose`, `/whoami` | `9965dde` | `audit_log` table (0008), `repos.audit`; `_audit()` helper in handlers logs only real changes; `is_admin()` in middlewares |
| 13 | Per-chat admin roles | `6efab16` | `is_admin(bot, chat, user_id, sender_chat)` in middlewares; empty `ADMIN_IDS` → private open, group admins via `get_chat_member` (5 min cache, errors not cached), anonymous admins via `sender_chat`; harness `session.members` |
| 14 | `/test` command | `08f6894` | `src/samples.py` (`sample_event(kind, project, env)`); admin-only; uses the chat's first concrete route for project/org/env and reports what the chat's filters would do |
| 15 | Web admin page | `84015ad` | `src/admin_web.py`, `GET /admin`, `ADMIN_TOKEN` (empty → 404); bearer / `X-Admin-Token` / `?token=`; no-store, CSP, no-referrer; `routes.list_all()`, `environments.list_all()` |
| 16 | Dead-letter retry | _next commit_ | failed rows now keep `text`; `delivery.retry_failed()` marks originals `retried` and logs a fresh row; `/retry_failed [N]` (admin); `POST /admin/retry` (token in form/header, not query) |

Migrations so far: `0001`…`0008`. Next revision id: `0009`.

## Remaining (suggested order)

Routing and management

Operations and observability
- [ ] **Metrics endpoint** — `/metrics` Prometheus text format, hand-rolled counters in `src/metrics.py` (received, deduplicated, rejected_signature, delivered, failed, skipped, queue_size gauge).
- [ ] **Postgres option** — replace `sqlite_insert` upserts in `repositories.py` with dialect-aware helper (`insert(...).on_conflict_do_*` for both via `sqlalchemy.dialects.postgresql`/`sqlite` chosen from `session.bind.dialect.name`); `make_url` already accepts full URLs; add `asyncpg` optional extra; make pragmas SQLite-only (already). Cannot be tested locally without Postgres — keep SQLite tests green.
- [ ] **Docker / compose / systemd / GitHub Actions** — `Dockerfile` (python:3.12-slim, uv), `docker-compose.yml` (volume for `data.db`), `deploy/sentry-telegram.service`, `.github/workflows/ci.yml` running pytest; `.dockerignore`.
- [ ] **Polling fallback** — `USE_WEBHOOK=false`: skip `set_webhook` (call `delete_webhook`), run `dp.start_polling` as a background task; still serve the Sentry HTTP endpoint. In `main.py`.
- [ ] **Startup self-check** — after start: `bot.get_webhook_info()` matches URL; if `DEFAULT_CHAT_ID` set, `get_chat` it and warn; log summary of routes/projects counts.

Polish
- [ ] **Localisation (en/ru/uz)** — `src/i18n.py` with dict-based catalogs; `chat_settings.language` column already exists; `/lang <code>`; apply to bot replies first, event formatting second.
- [ ] **`/stats`** — per-project counts over 24h/7d from `deliveries` (`count_by_status` exists; add group-by project).
- [ ] **Plain-text format mode** — `chat_settings.format` column exists; `/format plain|html`; add a `strip_html()` in formatters and send with `parse_mode=None` when plain.
- [ ] **Replay protection** — reject if `Sentry-Hook-Timestamp` older than `REPLAY_WINDOW_SECONDS` (default 300); keep dedup. In `src/web.py` before dedup.
- [ ] **Interactive issue actions** — inline buttons Resolve / Ignore / Assign-to-me / Open on issue messages; needs `SENTRY_API_TOKENS` per org label and `installations.org_slug`; PUT `/api/0/organizations/{org}/issues/{id}/`. Depends on threading (issue_id in deliveries) and multi-org. Put in `src/sentry/api.py` with aiohttp client; callbacks in a new `issue_router`.
- [ ] **README** — setup, Sentry internal-integration configuration (webhook URL, client secret, resources to enable), command reference, env var table, deployment notes.

## Conventions

- Tests: `tests/bot_harness.py` drives aiogram handlers with a fake session (`Harness(repos)`, `.command(..., reply_to=, document=)`, `.callback()`, `.upload()` for downloadable files); `tests/test_web.py` has the `client` fixture for the Sentry HTTP endpoint; `repos` fixture gives an in-memory DB.
- Every schema change = new file in `migrations/versions/` with a defensive `upgrade()` (check `has_table` / column names) and a model update; `tests/test_migrations.py::test_models_match_latest_migration` fails on drift.
- Commands that take user text must escape it (`html.escape`) and validate against `SLUG_RE` (defined in `src/route_io.py`, imported as `_SLUG_RE` in handlers).
- Admin-gated commands go on `admin_router`; read-only ones on `public_router`.
- Commands that change chat config call `_audit(repos, chat_id, user, action, details)` after a successful change (details are plain text; escaped on display).
- Config values live in `src/config.py`; document new ones in `.env.example`.
