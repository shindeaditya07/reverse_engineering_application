import pytest
from pydantic import ValidationError

from services.api.settings import Settings


def test_missing_database_url_fails_and_names_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_rejects_unknown_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(ValidationError, match="environment"):
        Settings(_env_file=None)  # type: ignore[call-arg]
