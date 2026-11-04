"""Typed settings. The only place environment variables are read (AGENTS.md section 3)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    log_level: str = "INFO"
    git_sha: str = "unknown"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/platform"


@lru_cache
def get_settings() -> Settings:
    return Settings()
