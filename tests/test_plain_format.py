from unittest.mock import AsyncMock, MagicMock

import pytest

from src.delivery import flush_digests, retry_failed, send_event
from src.samples import sample_event
from src.sentry.formatters import format_event, strip_html
from tests.bot_harness import GROUP, OTHER, Harness


def test_strip_html():
    assert strip_html('<b>Boom</b> <a href="https://x/?a=1&amp;b=2">T &lt;i&gt;</a>') == "Boom T <i> (https://x/?a=1&b=2)"
    assert strip_html('<a href="https://u">https://u</a>') == "https://u"
    assert strip_html("<code>a &amp;lt; b</code>") == "a &lt; b"  # no double unescape
    assert strip_html("<blockquote expandable>x\ny</blockquote>") == "x\ny"
    text = strip_html(format_event(sample_event("error")))
    assert "<" not in text.replace("<i>", "") and "(https://sentry.io/" in text


def _bot():
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=11))
    bot.edit_message_text = AsyncMock()
    return bot


async def test_plain_chat_gets_plain_text_but_html_is_stored(repos):
    await repos.routes.add("p", None, 10)
    await repos.routes.add("p", None, 20)
    await repos.chat_settings.update(20, format="plain")
    bot = _bot()
    event = sample_event("issue", "p")
    await send_event(bot, repos, event)
    calls = {c.args[0]: c for c in bot.send_message.await_args_list}
    assert "<b>" in calls[10].args[1] and "parse_mode" not in calls[10].kwargs
    assert "<b>" not in calls[20].args[1] and calls[20].kwargs["parse_mode"] is None
    [row] = await repos.deliveries.recent_for_chat(20)
    assert "<b>Issue CREATED</b>" in row["text"]  # canonical HTML kept for edits / retries

    # lifecycle update: the original is stamped, edited as plain text
    event.action, event.actor = "resolved", "Al"
    await send_event(bot, repos, event)
    edit = [c for c in bot.edit_message_text.await_args_list if c.kwargs["chat_id"] == 20][0]
    assert edit.kwargs["parse_mode"] is None
    assert "<b>" not in edit.args[0] and edit.args[0].endswith("✅ RESOLVED by Al")
    original = (await repos.deliveries.recent_for_chat(20))[-1]  # oldest row = the first post
    assert "<b>Issue CREATED</b>" in original["text"] and "<b>RESOLVED</b> by Al" in original["text"]


async def test_retry_and_digest_respect_format(repos):
    await repos.chat_settings.update(10, format="plain")
    await repos.deliveries.record(chat_id=10, resource="issue", action="created", project="p", environment=None,
                                  issue_id="1", title="t", status="failed", error="x", text="<b>bold</b> &amp;")
    bot = _bot()
    await retry_failed(bot, repos, 10)
    call = bot.send_message.await_args
    assert call.args[1] == "bold &" and call.kwargs["parse_mode"] is None

    await repos.routes.add("p", None, 10)
    [route] = await repos.routes.list_for_chat(10)
    await repos.digests.add(chat_id=10, route_id=route["id"], project="p", environment=None, issue_id="1",
                            resource="issue", action="created", level="error", title="T", web_url=None)
    await flush_digests(bot, repos, force=True)
    call = bot.send_message.await_args
    assert call.args[1].startswith("📰 Digest: 1 event across 1 issue") and call.kwargs["parse_mode"] is None


@pytest.fixture
def h(repos):
    return Harness(repos)


async def test_format_command_and_test_preview(h, repos):
    await h.command("/format markdown")
    assert "Usage" in h.session.last_text
    await h.command("/format plain", user=OTHER)
    assert "not allowed" in h.session.last_text

    await h.command("/format plain")
    assert "Alert format set to <code>plain</code>" in h.session.last_text
    assert (await repos.chat_settings.get(GROUP.id))["format"] == "plain"
    await h.command("/test")
    sample = h.session.sent[-2]
    assert sample.parse_mode is None and "Issue CREATED" in sample.text and "<b>" not in sample.text

    await h.command("/format html")
    await h.command("/test")
    assert "<b>Issue CREATED</b>" in h.session.sent[-2].text
    actions = [e["details"] for e in await repos.audit.recent_for_chat(GROUP.id) if e["action"] == "settings.format"]
    assert actions == ["html", "plain"]
