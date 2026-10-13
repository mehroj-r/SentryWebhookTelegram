# Sentry → Telegram

A Telegram bot that receives Sentry webhooks and posts them to Telegram chats,
with per-chat routing, noise control, digests, threading and inline issue actions.

- **Routing**: send each Sentry project (or `org/project`, or a wildcard like `backend-*`)
  and environment to any number of chats or forum topics. Unmatched events go to `DEFAULT_CHAT_ID`.
- **Noise control**: minimum level, action allowlist, temporary mutes, burst collapsing,
  periodic digests and per-chat quiet hours.
- **Threading**: follow-up events reply to the first message about an issue, and the original
  message is stamped with its latest status (✅ RESOLVED by Alice).
- **Issue actions** (optional): Resolve / Ignore / Assign to me / Open in Sentry buttons.
- **Operations**: delivery log (`/last`, `/stats`), retry of failed sends, audit log,
  web admin page, Prometheus metrics, SQLite or PostgreSQL.
- **Languages**: English, Russian, Uzbek (`/lang`), HTML or plain-text alerts (`/format`).

## Quick start

```bash
cp .env.example .env        # fill in BOT_TOKEN, WEBHOOK_*, SENTRY_CLIENT_SECRET
uv venv && uv pip install -r pyproject.toml
.venv/bin/python main.py
```

or with Docker:

```bash
docker compose up -d --build
```

Database migrations run automatically on startup. On start, the bot logs a self-check
covering the token, webhook URL, `DEFAULT_CHAT_ID` reachability and whether any routes exist.

### Telegram

1. Create a bot with [@BotFather](https://t.me/BotFather) and put the token in `BOT_TOKEN`.
2. Expose the server over HTTPS (reverse proxy such as Caddy or nginx in front of `PORT`)
   and set `WEBHOOK_BASE_URL`. The bot registers `WEBHOOK_BASE_URL + TG_WEBHOOK_PATH`
   with Telegram on startup.
   - No public HTTPS for the bot? Set `USE_WEBHOOK=false` and it long-polls Telegram
     instead. Sentry still has to reach `SENTRY_WEBHOOK_PATH`.
3. Add the bot to your group and run `/subscribe` (or `/add_route <project>`).
   In forum supergroups, run it inside the topic you want alerts in.

### Sentry

Create an **internal integration** (Settings → Developer Settings → Custom Integrations → New Internal Integration):

| Field | Value |
|---|---|
| Webhook URL | `https://your-domain.example.com/sentry/webhook` (`SENTRY_WEBHOOK_PATH`) |
| Alert Rule Action | on (lets alert rules send to this integration) |
| Webhooks | `issue`, `error`, `comment` as needed |
| Permissions | Issue & Event: **Read** (or **Read & Write** for the action buttons) |

Copy the integration's **Client Secret** into `SENTRY_CLIENT_SECRET`. Requests with a wrong
`Sentry-Hook-Signature` are rejected with 401.

Then, in your alert rules (issue alerts and metric alerts), add the action
"Send a notification via *your integration*".

Supported resources: `issue` (created / resolved / assigned / archived / unresolved),
`error`, `event_alert`, `metric_alert`, `comment` and `installation`. Anything else is
posted in a generic format.

**Release / deploy notifications** come from your CI rather than Sentry. POST to the
same endpoint, signed with the client secret:

```bash
BODY='{"action":"deployed","data":{"release":{"version":"backend@1.4.2","projects":["backend"],"commit_count":12},"deploy":{"environment":"production"}}}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SENTRY_CLIENT_SECRET" -hex | sed 's/^.* //')
curl -X POST https://your-domain.example.com/sentry/webhook \
  -H "Sentry-Hook-Resource: deploy" -H "Sentry-Hook-Signature: $SIG" \
  -H "Content-Type: application/json" -d "$BODY"
```

**Several organisations:** install an integration in each and set
`SENTRY_CLIENT_SECRETS=acme:secret1,beta:secret2` (or JSON). The label is shown as
`[acme]` on messages and can prefix routes (`/add_route acme/backend`).

**Action buttons:** create a token for the integration with Issue & Event *Read & Write*
and set `SENTRY_API_TOKEN` + `SENTRY_ORG_SLUG` (or `SENTRY_API_TOKENS=acme:tok1,beta:tok2`).
For self-hosted Sentry, also set `SENTRY_API_URL`. Users link their Sentry account for
"Assign to me" with `/sentry_user you@example.com`.

## Commands

Commands that change configuration are limited to admins. If `ADMIN_IDS` is set, only
those users count as admins, everywhere. If it's empty, anyone may configure the bot in a
private chat, and in groups only the group's Telegram admins may. The admin status is
cached for 5 minutes. The remaining commands are read-only and open to everyone.

| Command | Who | What |
|---|---|---|
| `/subscribe` | admin | Pick a project and environment for this chat from the ones Sentry has sent |
| `/add_route <slug\|org/slug\|pattern> [env]` | admin | Add a route by hand (`backend-*`, `*` work) |
| `/routes` | all | List routes, tap to remove (removal is admin-only) |
| `/routes verbose` | all | Route details plus the last 10 configuration changes |
| `/filter <slug\|all> level=<min> actions=<a,b>` / `clear` | admin | Minimum level and action allowlist |
| `/mute <30m\|2h\|1d> [slug]`, `/unmute [slug]` | admin | Pause alerts |
| `/digest <slug\|all> <minutes\|off>` | admin | Batch events into one message every N minutes |
| `/settings` | all | Show chat settings |
| `/tz <Area/City>` | admin | Chat timezone (for times shown and quiet hours) |
| `/quiet <22:00-08:00\|off>` | admin | Quiet hours: non-fatal events are held and sent as a digest afterwards |
| `/lang <en\|ru\|uz>` | admin | Language of bot replies and alerts |
| `/format <html\|plain>` | admin | Alert formatting |
| `/export`, `/import` | all / admin | Download routes as JSON; load them by sending the file with caption `/import` |
| `/test [issue\|error\|event_alert\|metric_alert\|release]` | admin | Post a sample alert and say whether this chat's filters would deliver it |
| `/last` | all | Last 10 deliveries to this chat, with errors |
| `/stats` | all | Delivery counts for the last 24 h and 7 days, top projects |
| `/retry_failed [N]` | admin | Re-send the last N failed deliveries |
| `/sentry_user <username\|email\|off>` | everyone (for themselves) | Sentry account used by "Assign to me" |
| `/chat_id`, `/whoami` | all | IDs and your admin status |

## Configuration

All settings are environment variables (or `.env`). See `.env.example` for a commented template.

| Variable | Default | Description |
|---|---|---|
| `BOT_TOKEN` | — | Telegram bot token (required) |
| `USE_WEBHOOK` | `true` | `false` = long-poll Telegram instead of receiving its webhook |
| `WEBHOOK_BASE_URL` | — | Public `https://` base URL (required in webhook mode) |
| `WEBHOOK_SECRET_TOKEN` | — | Secret Telegram sends with each update, 1–256 of `A-Za-z0-9_-` (required in webhook mode) |
| `TG_WEBHOOK_PATH` | `/telegram/webhook` | Path for Telegram updates |
| `SENTRY_WEBHOOK_PATH` | `/sentry/webhook` | Path for Sentry webhooks |
| `HOST`, `PORT` | `0.0.0.0`, `8080` | Listen address |
| `SENTRY_CLIENT_SECRET` | — | Integration client secret (this or `SENTRY_CLIENT_SECRETS` is required) |
| `SENTRY_CLIENT_SECRETS` | — | `label:secret,…` or JSON, for several orgs/integrations |
| `SENTRY_API_URL` | `https://sentry.io` | Sentry Web API base (self-hosted) |
| `SENTRY_API_TOKEN`, `SENTRY_ORG_SLUG` | — | Enable action buttons for one org |
| `SENTRY_API_TOKENS` | — | `org:token,…` or JSON, for several orgs |
| `DB_PATH` | `data.db` | SQLite file, `:memory:`, or `postgresql://user:pass@host/db` (install with `--extra postgres`) |
| `DEFAULT_CHAT_ID` | — | Chat for events no route matches |
| `ADMIN_IDS` | — | Telegram user ids allowed to configure the bot everywhere |
| `ADMIN_TOKEN` | — | Enables the `/admin` web page |
| `METRICS_TOKEN` | — | If set, `/metrics` requires `Authorization: Bearer <token>` |
| `REPLAY_WINDOW_SECONDS` | `300` | Reject webhooks whose `Sentry-Hook-Timestamp` is further than this from now (0 = off) |
| `BURST_WINDOW_SECONDS` | `600` | Collapse repeats of one issue within this window into a "+N more" line (0 = off) |
| `QUEUE_MAX_SIZE` | `1000` | Pending deliveries before Sentry gets `503 Retry-After` |
| `MAX_BODY_BYTES` | `10485760` | Largest accepted webhook body |
| `SEEN_REQUEST_TTL_DAYS` | `7` | How long Request-IDs are remembered for de-duplication |

## HTTP endpoints

| Path | Purpose |
|---|---|
| `POST /sentry/webhook` | Sentry webhooks (signature-checked, de-duplicated by `Request-ID`) |
| `POST /telegram/webhook` | Telegram updates (webhook mode only) |
| `GET /health` | `{"status": "ok", "queue_size": N}` |
| `GET /metrics` | Prometheus metrics: webhooks received / rejected (by reason) / de-duplicated, deliveries by status, queue size |
| `GET /admin` | Admin page: routes across chats, projects, installations, recent deliveries with a status filter, and a button to retry failed deliveries. Pass `ADMIN_TOKEN` as `Authorization: Bearer …`, `X-Admin-Token`, or `?token=…` |

## Deployment

- **Docker**: `Dockerfile` (Python 3.12, non-root, data in the `/data` volume, health check)
  and `docker-compose.yml`. For PostgreSQL, run `docker compose --profile postgres up -d`
  and set `DB_PATH=postgresql://sentry:sentry@postgres/sentry`.
- **systemd**: see `deploy/sentry-telegram.service` (install steps in its header).
- Shutting down on `SIGTERM` stops intake first, then drains the delivery queue for up to 15 s.
- The delivery log and audit log are not pruned automatically yet. On a busy installation,
  delete old rows from `deliveries` and `audit_log` periodically.

## Development

```bash
uv venv && uv pip install -r pyproject.toml --extra dev --extra postgres
.venv/bin/python -m pytest
# against PostgreSQL as well:
TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5432/test .venv/bin/python -m pytest
```

Schema changes go in `migrations/versions/` (Alembic). `tests/test_migrations.py` fails if
the models and migrations drift apart. User-facing text lives in `src/i18n.py`, with each key
in all three languages. `PROGRESS.md` tracks the roadmap and conventions.
