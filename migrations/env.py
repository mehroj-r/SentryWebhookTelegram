"""
Alembic environment.

Two entry points:
- CLI (`alembic upgrade head`): builds its own async engine from Settings.
- Programmatic (Database.connect): the app hands us an already-open sync
  connection via `config.attributes["connection"]`, so migrations run inside
  the application's engine at startup.
"""
from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from src.db.models import Base

config = context.config
target_metadata = Base.metadata


def _url_from_settings() -> str:
    from src.config import settings
    from src.db.database import make_url

    return make_url(settings.db_path)


def run_migrations_offline() -> None:
    context.configure(
        url=_url_from_settings(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # SQLite cannot ALTER most things in place
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _url_from_settings()
    connectable = async_engine_from_config(section, prefix="sqlalchemy.")
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        do_run_migrations(connection)
    else:
        asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
