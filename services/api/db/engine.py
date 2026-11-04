"""Engine construction. One style: synchronous SQLAlchemy 2.0 with psycopg (ADR-0006)."""

from sqlalchemy import Engine, create_engine


def sqlalchemy_url(url: str) -> str:
    """Accept a plain ``postgresql://`` URL and select the psycopg 3 driver."""
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def make_engine(url: str) -> Engine:
    """Create an engine with the pool settings from AGENTS.md section 4."""
    return create_engine(
        sqlalchemy_url(url),
        pool_pre_ping=True,  # test a connection before use; replace dead ones
        pool_recycle=1800,  # retire connections before servers or networks kill them
        pool_timeout=10,  # fail fast instead of hanging
        pool_size=5,
        max_overflow=5,
    )
