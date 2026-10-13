from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

import main
from src.config import settings
from src.db.models import AuditEntry, Delivery


async def _age(repos, model, column, days):
    async with repos.deliveries._sessionmaker() as session:
        await session.execute(sa.update(model).values({column: datetime.now(timezone.utc) - timedelta(days=days)}))
        await session.commit()


async def _rows(repos, model):
    async with repos.deliveries._sessionmaker() as session:
        return await session.scalar(sa.select(sa.func.count()).select_from(model))


async def _seed(repos):
    await repos.deliveries.record(chat_id=1, resource="issue", action="created", project="p", environment=None,
                                  issue_id="1", title="old", status="sent")
    await repos.audit.record(1, 7, "route.add", "old")
    await _age(repos, Delivery, "created_at", 40)
    await _age(repos, AuditEntry, "ts", 40)
    await repos.deliveries.record(chat_id=1, resource="issue", action="created", project="p", environment=None,
                                  issue_id="2", title="new", status="sent")
    await repos.audit.record(1, 7, "route.add", "new")


async def test_purge_once_applies_retention(repos, monkeypatch):
    monkeypatch.setattr(settings, "log_retention_days", 30)
    await _seed(repos)
    removed = await main.purge_once(repos)
    assert removed == {"seen_requests": 0, "deliveries": 1, "audit_log": 1}
    assert [r["title"] for r in await repos.deliveries.recent_for_chat(1)] == ["new"]
    assert [e["details"] for e in await repos.audit.recent_for_chat(1)] == ["new"]


async def test_zero_keeps_logs_forever(repos, monkeypatch):
    monkeypatch.setattr(settings, "log_retention_days", 0)
    await _seed(repos)
    assert await main.purge_once(repos) == {"seen_requests": 0}
    assert await _rows(repos, Delivery) == 2 and await _rows(repos, AuditEntry) == 2
