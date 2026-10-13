from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from src.db.models import Delivery
from tests.bot_harness import GROUP, OTHER, Harness


@pytest.fixture
def h(repos):
    return Harness(repos)


async def _rec(repos, project, status, chat_id=GROUP.id, resource="issue", age=None):
    rid = await repos.deliveries.record(
        chat_id=chat_id, resource=resource, action="created", project=project, environment=None,
        issue_id=None, title="t", status=status,
    )
    if age:
        async with repos.deliveries._sessionmaker() as session:
            await session.execute(
                sa.update(Delivery).where(Delivery.id == rid).values(created_at=datetime.now(timezone.utc) - age)
            )
            await session.commit()


async def test_counts_by_project(repos):
    await _rec(repos, "api", "sent")
    await _rec(repos, "api", "failed")
    await _rec(repos, None, "sent")
    await _rec(repos, None, "sent", resource="digest")  # digest sends are not events
    await _rec(repos, "api", "sent", chat_id=999)
    await _rec(repos, "api", "sent", age=timedelta(days=2))
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    assert await repos.deliveries.counts_by_project(GROUP.id, since) == {
        "api": {"sent": 1, "failed": 1}, "?": {"sent": 1},
    }


async def test_stats_command(h, repos):
    await h.command("/stats")
    assert "No events" in h.session.last_text

    for _ in range(3):
        await _rec(repos, "api", "sent")
    await _rec(repos, "api", "failed")
    await _rec(repos, "web", "skipped", age=timedelta(days=3))
    await _rec(repos, "web", "digest", age=timedelta(days=3))
    await _rec(repos, "web", "retried", age=timedelta(days=3))  # superseded, not counted
    await _rec(repos, "old", "sent", age=timedelta(days=9))     # outside the window

    await h.command("/stats", user=OTHER)  # read-only, public
    text = h.session.last_text
    assert "<b>Last 24 hours</b>: 4 event(s) — ✅ 3 sent, ❌ 1 failed" in text
    assert "<b>Last 7 days</b>: 6 event(s)" in text and "⏭ 1 skipped" in text and "📰 1 in digests" in text
    assert text.index("<code>api</code> — 4 (24h: 4)  ❌1") < text.index("<code>web</code> — 2 (24h: 0)  ⏭1 📰1")
    assert "old" not in text


async def test_stats_localised(h, repos):
    await repos.chat_settings.update(GROUP.id, language="ru")
    await _rec(repos, "api", "sent")
    await h.command("/stats")
    assert "<b>За 24 часа</b>: событий 1 — ✅ 1 доставлено" in h.session.last_text
