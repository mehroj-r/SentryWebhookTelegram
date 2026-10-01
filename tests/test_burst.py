from unittest.mock import AsyncMock, MagicMock

from src.burst import BurstCollapser
from src.delivery import _flush_bursts, send_event
from src.sentry.parser import ParsedEvent


def _ev(**kw):
    base = dict(resource="error", action="created", project_slug="p", project_ref_id=None,
                environment="prod", title="Boom", web_url=None, issue_id="7")
    base.update(kw)
    return ParsedEvent(**base)


def test_collapser_window_and_summary():
    c = BurstCollapser(window_s=60)
    assert c.check(_ev(), 1, now=0) is True
    assert c.check(_ev(), 1, now=10) is False
    assert c.check(_ev(), 1, now=20) is False
    assert c.check(_ev(issue_id="other"), 1, now=20) is True  # different issue
    assert c.check(_ev(), 2, now=20) is True  # different chat
    assert list(c.flush_due(now=30)) == []  # window not elapsed
    [summary] = list(c.flush_due(now=61))
    assert summary.count == 2 and summary.chat_id == 1 and summary.issue_id == "7"
    assert list(c.flush_due(now=62)) == []  # reported once


def test_collapser_ignores_issue_hooks_and_disabled():
    c = BurstCollapser(window_s=60)
    assert c.check(_ev(resource="issue"), 1, now=0) and c.check(_ev(resource="issue"), 1, now=1)
    off = BurstCollapser(window_s=0)
    assert off.check(_ev(), 1, now=0) and off.check(_ev(), 1, now=1)


async def test_worker_path_records_collapsed_and_sends_summary(repos):
    await repos.routes.add("p", None, 10)
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    c = BurstCollapser(window_s=60)
    await send_event(bot, repos, _ev(), c)
    await send_event(bot, repos, _ev(), c)
    await send_event(bot, repos, _ev(), c)
    assert bot.send_message.await_count == 1
    rows = await repos.deliveries.recent_for_chat(10)
    assert sorted(r["status"] for r in rows) == ["sent", "skipped", "skipped"]

    await _flush_bursts(bot, repos, c, force=True)
    assert bot.send_message.await_count == 2
    text = bot.send_message.call_args.args[1]
    assert "+2 more" in text and "Boom" in text
    assert bot.send_message.call_args.kwargs["reply_parameters"].message_id == 1
