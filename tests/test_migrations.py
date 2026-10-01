import sqlalchemy as sa

from src.db import Database
from src.db.models import Base


async def _table_names(db: Database) -> set[str]:
    async with db.sessionmaker() as session:
        rows = await session.execute(sa.text("SELECT name FROM sqlite_master WHERE type='table'"))
        return {r[0] for r in rows}


async def test_fresh_database_is_migrated(tmp_path):
    db = Database(str(tmp_path / "fresh.db"))
    await db.connect()
    names = await _table_names(db)
    assert {"routes", "projects", "environments", "seen_requests", "alembic_version"} <= names
    await db.close()


async def test_pre_alembic_database_is_adopted(tmp_path):
    """A DB created with metadata.create_all (old versions) must upgrade cleanly."""
    path = str(tmp_path / "legacy.db")
    legacy = Database(path)
    legacy_tables = [Base.metadata.tables[n] for n in ("routes", "projects", "environments", "seen_requests")]
    async with legacy._engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=legacy_tables))
    await legacy.close()

    db = Database(path)
    await db.connect()  # must not fail on "table already exists"
    assert "alembic_version" in await _table_names(db)
    # second start is a no-op
    await db.connect()
    await db.close()


def test_models_match_latest_migration(tmp_path):
    """Autogenerate must find no drift between models and migrations."""
    import asyncio
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    path = str(tmp_path / "drift.db")

    async def _prepare():
        db = Database(path)
        await db.connect()
        await db.close()

    asyncio.run(_prepare())
    engine = sa.create_engine(f"sqlite:///{path}")
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        diff = compare_metadata(ctx, Base.metadata)
    engine.dispose()
    assert diff == [], diff
