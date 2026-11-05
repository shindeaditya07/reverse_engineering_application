import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from services.api.settings import get_settings
from services.db.session import make_engine


def _require_db() -> bool:
    return os.environ.get("REQUIRE_DB") == "1"


@pytest.fixture(scope="session")
def migrated_database() -> None:
    """Apply migrations once. Without a database: skip locally, fail when REQUIRE_DB=1 (CI)."""
    try:
        command.upgrade(Config("alembic.ini"), "head")
    except Exception as error:
        if _require_db():
            pytest.fail(f"REQUIRE_DB=1 but the database is unavailable: {error}")
        pytest.skip(f"no database at DATABASE_URL: {type(error).__name__}")


@pytest_asyncio.fixture
async def engine(migrated_database: None) -> AsyncIterator[AsyncEngine]:
    engine = make_engine(get_settings().database_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def connection(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """One transaction per test, always rolled back, so tests never leave rows behind."""
    async with engine.connect() as conn:
        transaction = await conn.begin()
        yield conn
        await transaction.rollback()
