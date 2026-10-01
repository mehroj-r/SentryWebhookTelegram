from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Connection, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = _PROJECT_ROOT / "alembic.ini"


def make_url(path: str) -> str:
    if path == ":memory:":
        return "sqlite+aiosqlite:///:memory:"
    if "://" in path:  # a full SQLAlchemy URL was given
        return path
    return f"sqlite+aiosqlite:///{path}"


def _run_alembic_upgrade(connection: Connection) -> None:
    """Run `alembic upgrade head` on an existing (sync-adapted) connection."""
    cfg = AlembicConfig(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_PROJECT_ROOT / "migrations"))
    cfg.attributes["connection"] = connection
    command.upgrade(cfg, "head")


class Database:
    """
    Infrastructure core: owns the async engine and sessionmaker.

    Responsibilities:
    - build the engine from a path, a full URL, or ":memory:"
    - bring the schema up to date on connect() (Alembic migrations; for the
      in-memory test database the metadata is created directly)
    - tear down on close()
    - expose sessionmaker so Repositories can be constructed from it

    Domain query logic lives in src/db/repositories.py.
    """

    def __init__(self, path: str) -> None:
        url = make_url(path)
        self._is_sqlite = url.startswith("sqlite")
        self._in_memory = url.endswith(":memory:")
        connect_args = {"timeout": 30} if self._is_sqlite else {}
        # `timeout` is SQLite's busy timeout: concurrent writers wait instead of
        # failing immediately with "database is locked".
        self._engine = create_async_engine(url, echo=False, connect_args=connect_args)
        self._sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False
        )

        if self._is_sqlite and not self._in_memory:

            @event.listens_for(self._engine.sync_engine, "connect")
            def _set_sqlite_pragmas(dbapi_connection, _record) -> None:  # type: ignore[no-untyped-def]
                # WAL lets the web handler read while the worker writes;
                # synchronous=NORMAL is safe under WAL and much faster.
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.close()

    @property
    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        return self._sessionmaker

    @property
    def url(self) -> str:
        return str(self._engine.url)

    async def connect(self, migrate: bool = True) -> None:
        async with self._engine.begin() as conn:
            if migrate and not self._in_memory:
                await conn.run_sync(_run_alembic_upgrade)
            else:
                await conn.run_sync(Base.metadata.create_all)
        log.info("Database ready: %s", self._engine.url)

    async def close(self) -> None:
        await self._engine.dispose()
