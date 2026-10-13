from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from src.bot.issue_actions import IssueCallback, issue_keyboard
from src.bot.keyboards import key_for
from src.config import settings
from src.delivery import send_event
from src.samples import sample_event
from src.sentry.api import SentryAPI, pick_org
from tests.bot_harness import GROUP, OTHER, Harness


@pytest.fixture
def one_org(monkeypatch):
    monkeypatch.setattr(settings, "sentry_api_tokens", {"acme": "tok"})


# ── API client ─────────────────────────────────────────────────────────────────


@pytest.fixture
async def fake_sentry():
    seen = []

    async def handler(request):
        seen.append((request.method, request.path, request.headers.get("Authorization"), await request.json()))
        if request.match_info["issue"] == "403":
            return web.json_response({"detail": "You do not have permission"}, status=403)
        return web.json_response({"id": request.match_info["issue"]})

    app = web.Application()
    app.router.add_put("/api/0/organizations/{org}/issues/{issue}/", handler)
    server = TestServer(app)
    await server.start_server()
    yield str(server.make_url("")), seen
    await server.close()


async def test_api_update_issue(fake_sentry):
    base, seen = fake_sentry
    api = SentryAPI(base + "/", {"acme": "tok"})
    assert await api.update_issue("acme", "42", {"status": "resolved"}) == (True, "")
    assert seen == [("PUT", "/api/0/organizations/acme/issues/42/", "Bearer tok", {"status": "resolved"})]
    ok, err = await api.update_issue("acme", "403", {"status": "ignored"})
    assert not ok and err == "HTTP 403: You do not have permission"
    assert (await api.update_issue("other", "42", {}))[0] is False
    assert (await api.update_issue("acme", "../x", {}))[1] == "invalid issue id"
    assert len(seen) == 2
    await api.close()


async def test_api_network_error():
    api = SentryAPI("http://127.0.0.1:9", {"acme": "tok"})
    ok, err = await api.update_issue("acme", "1", {"status": "resolved"})
    assert not ok and err.startswith("network error")
    await api.close()


def test_pick_org():
    assert pick_org({}, "acme") is None
    assert pick_org({"acme": "t"}, None) == "acme"  # single org: everything belongs to it
    assert pick_org({"acme": "t", "beta": "u"}, "beta") == "beta"
    assert pick_org({"acme": "t", "beta": "u"}, "gamma") is None


# ── keyboard ───────────────────────────────────────────────────────────────────


def _buttons(markup):
    return [b for row in markup.inline_keyboard for b in row]


def test_keyboard_rules(one_org, monkeypatch):
    event = sample_event("issue")
    buttons = _buttons(issue_keyboard(event, "en"))
    assert [b.text for b in buttons] == ["✅ Resolve", "🙈 Ignore", "👤 Assign to me", "🔗 Open in Sentry"]
    data = IssueCallback.unpack(buttons[0].callback_data)
    assert (data.action, data.issue, data.org) == ("r", "1234567", key_for("acme"))
    assert all(len(b.callback_data.encode()) <= 64 for b in buttons[:3])
    assert buttons[3].url == event.web_url
    assert _buttons(issue_keyboard(event, "ru"))[0].text == "✅ Решено"

    assert issue_keyboard(sample_event("metric_alert"), "en") is None
    event.action = "resolved"
    assert issue_keyboard(event, "en") is None  # lifecycle updates are threaded replies
    assert issue_keyboard(event, "en", stamping=True) is not None
    event.action, event.issue_id = "created", "abc"
    assert issue_keyboard(event, "en") is None

    monkeypatch.setattr(settings, "sentry_api_tokens", {})
    assert issue_keyboard(sample_event("issue"), "en") is None


# ── delivery ───────────────────────────────────────────────────────────────────


async def test_buttons_on_first_post_and_stamping(one_org, repos):
    await repos.routes.add("p", None, 10)
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=5))
    bot.edit_message_text = AsyncMock()

    event = sample_event("error", "p")
    await send_event(bot, repos, event)
    assert bot.send_message.await_args.kwargs["reply_markup"] is not None
    await send_event(bot, repos, sample_event("error", "p"))  # same issue again: threaded, no buttons
    assert "reply_markup" not in bot.send_message.await_args.kwargs

    issue = sample_event("issue", "p")
    issue.action, issue.actor, issue.extra = "assigned", "Al", {"assigned_to": "Bob"}
    await send_event(bot, repos, issue)
    assert bot.edit_message_text.await_args.kwargs["reply_markup"] is not None  # still open: keep buttons
    issue.action = "resolved"
    await send_event(bot, repos, issue)
    assert "reply_markup" not in bot.edit_message_text.await_args.kwargs  # resolved: buttons removed


# ── callbacks / commands ───────────────────────────────────────────────────────


@pytest.fixture
def h(repos):
    harness = Harness(repos)
    api = MagicMock(orgs=["acme"])
    api.update_issue = AsyncMock(return_value=(True, ""))
    harness.dp["sentry_api"] = api
    harness.api = api
    return harness


async def _alerted(repos, issue="77", chat_id=GROUP.id):
    await repos.deliveries.record(chat_id=chat_id, resource="issue", action="created", project="p",
                                  environment=None, issue_id=issue, title="t", status="sent", tg_message_id=1)


def _cb(action, issue="77", org="acme"):
    return IssueCallback(action=action, issue=issue, org=key_for(org)).pack()


async def test_resolve_and_ignore(h, repos):
    await _alerted(repos)
    await h.callback(_cb("r"))
    h.api.update_issue.assert_awaited_with("acme", "77", {"status": "resolved"})
    assert h.session.answers[-1].text == "✅ Resolved in Sentry"
    await h.callback(_cb("i"))
    h.api.update_issue.assert_awaited_with("acme", "77", {"status": "ignored"})
    actions = [(e["action"], e["details"]) for e in await repos.audit.recent_for_chat(GROUP.id)]
    assert ("issue.resolve", "acme/77") in actions and ("issue.ignore", "acme/77") in actions


async def test_forged_or_unknown_callbacks_do_nothing(h, repos):
    await _alerted(repos, chat_id=999)  # another chat got this issue, not us
    await h.callback(_cb("r"))
    assert "no alert for that issue" in h.session.answers[-1].text
    await _alerted(repos)
    await h.callback(_cb("r", org="evil"))
    assert "isn't configured" in h.session.answers[-1].text
    await h.callback(_cb("r"), user=OTHER)  # non-admin
    assert "not allowed" in h.session.answers[-1].text
    h.api.update_issue.assert_not_awaited()


async def test_assign_to_me_needs_identity(h, repos):
    await _alerted(repos)
    await h.callback(_cb("a"))
    assert "/sentry_user" in h.session.answers[-1].text and h.session.answers[-1].show_alert
    h.api.update_issue.assert_not_awaited()

    await h.command("/sentry_user")
    assert "No Sentry user linked" in h.session.last_text
    await h.command("/sentry_user <b>")
    assert "Usage" in h.session.last_text
    await h.command("/sentry_user dev@example.com")
    assert "<code>dev@example.com</code>" in h.session.last_text
    await h.command("/sentry_user", user=OTHER)  # per user, and not admin-gated
    assert "No Sentry user linked" in h.session.last_text

    await h.callback(_cb("a"))
    h.api.update_issue.assert_awaited_with("acme", "77", {"assignedTo": "dev@example.com"})
    assert h.session.answers[-1].text == "👤 Assigned to you"

    await h.command("/sentry_user off")
    assert await repos.identities.get(1) is None


async def test_api_failure_is_reported(h, repos):
    await _alerted(repos)
    h.api.update_issue = AsyncMock(return_value=(False, "HTTP 403: nope"))
    await h.callback(_cb("r"))
    assert h.session.answers[-1].text == "Sentry refused: HTTP 403: nope" and h.session.answers[-1].show_alert
    assert await repos.audit.recent_for_chat(GROUP.id) == []
