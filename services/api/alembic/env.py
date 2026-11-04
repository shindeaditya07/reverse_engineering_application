"""Alembic environment. Migrations run as their own step, never during API start-up."""

import os

from alembic import context

from services.api.db.engine import make_engine
from services.api.db.tables import metadata

target_metadata = metadata


def _url() -> str:
    # The one place besides Settings that names DATABASE_URL: migrations must run without
    # building the whole application's settings (which may need other variables).
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set")
    return url


def run_migrations_online() -> None:
    """Run migrations against the database in DATABASE_URL."""
    connectable = context.config.attributes.get("connection")
    if connectable is None:
        engine = make_engine(_url())
        with engine.connect() as connection:
            _run(connection)
        engine.dispose()
    else:
        _run(connectable)


def _run(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


run_migrations_online()
