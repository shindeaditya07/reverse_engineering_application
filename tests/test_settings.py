import pytest

from services.api.settings import Settings


def test_defaults_are_local() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.app_env == "local"


def test_environment_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    assert Settings(_env_file=None).app_env == "staging"  # type: ignore[call-arg]


def test_get_settings_is_cached() -> None:
    from services.api.settings import get_settings

    assert get_settings() is get_settings()
