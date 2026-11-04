"""Async engine and session factory. Resilience settings per AGENTS.md section 4."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from services.api.settings import get_settings


def make_engine(url: str | None = None) -> AsyncEngine:
    return create_async_engine(
        url or get_settings().database_url,
        pool_pre_ping=True,
        pool_recycle=1800,
    )


@asynccontextmanager
async def session_scope(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """One transaction: commit on success, roll back on any error."""
    async with async_sessionmaker(engine, expire_on_commit=False)() as session, session.begin():
        yield session
