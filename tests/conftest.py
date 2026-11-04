"""Shared fixtures. Database tests need TEST_DATABASE_URL pointing at an empty Postgres 16
database; without it they are skipped (CI sets it from a service container)."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

from services.api.db.engine import make_engine

ROOT = Path(__file__).resolve().parents[1]


def _alembic_config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "services" / "api" / "alembic"))
    return config


@pytest.fixture
def migrated_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    """A database migrated to head, rebuilt from scratch for every test."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    monkeypatch.setenv("DATABASE_URL", url)
    config = _alembic_config()
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = make_engine(url)
    yield engine
    engine.dispose()
