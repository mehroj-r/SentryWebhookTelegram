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

from src.db import Database, Repositories


@pytest.fixture
async def repos():
    db = Database(":memory:")
    await db.connect()
    yield Repositories(db.sessionmaker)
    await db.close()
