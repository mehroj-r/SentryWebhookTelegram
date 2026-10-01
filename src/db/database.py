from __future__ import annotations

import logging

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

log = logging.getLogger(__name__)


class Database:
    """
    Infrastructure core: owns the async engine and sessionmaker.

    Responsibilities:
    - build the engine from a path or ":memory:"
    - create all tables on connect()
    - tear down on close()
    - expose sessionmaker so Repositories can be constructed from it

    Domain query logic lives in src/db/repositories.py.
    """

    def __init__(self, path: str) -> None:
        url = (
            "sqlite+aiosqlite:///:memory:"
            if path == ":memory:"
            else f"sqlite+aiosqlite:///{path}"
        )
        # `timeout` is SQLite's busy timeout: concurrent writers wait instead of
        # failing immediately with "database is locked".
        self._engine = create_async_engine(
            url, echo=False, connect_args={"timeout": 30}
        )
        self._sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False
        )

        if path != ":memory:":

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

    async def connect(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        log.info("Database ready: %s", self._engine.url)

    async def close(self) -> None:
        await self._engine.dispose()
