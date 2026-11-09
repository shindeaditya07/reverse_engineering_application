"""Typed settings. The only place environment variables are read (AGENTS.md section 3)."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    log_level: str = "INFO"
    git_sha: str = "unknown"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/platform"
    snapshot_dir: str = ".snapshots"
    github_token: SecretStr | None = None
    # Local model server, OpenAI-compatible. Must be loopback or a private address (SEC-2.1).
    model_endpoint: str = "http://127.0.0.1:11434/v1"
    model_name: str = "local-model"


@lru_cache
def get_settings() -> Settings:
    return Settings()
