import os

# Settings are instantiated at import time; give them valid values before any src import.
os.environ.setdefault("BOT_TOKEN", "123:TEST")
os.environ.setdefault("WEBHOOK_SECRET_TOKEN", "test_secret")
os.environ.setdefault("WEBHOOK_BASE_URL", "https://example.test/")
os.environ.setdefault("SENTRY_CLIENT_SECRET", "sentry_secret")
os.environ.setdefault("SENTRY_CLIENT_SECRETS", "acme:acme_secret")
os.environ.setdefault("ADMIN_IDS", "1,2")
os.environ.setdefault("DB_PATH", ":memory:")

import pytest
import sqlalchemy as sa

from src.db import Database, Repositories
from src.db.models import Base

# Run the suite against PostgreSQL with e.g.
#   TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5432/test pytest
# (the database is migrated, and every table is truncated before each test).
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
async def repos():
    db = Database(TEST_DATABASE_URL or ":memory:")
    await db.connect()
    if TEST_DATABASE_URL:
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        async with db.sessionmaker() as session:
            await session.execute(sa.text(f"TRUNCATE {tables} RESTART IDENTITY"))
            await session.commit()
    yield Repositories(db.sessionmaker)
    await db.close()
