"""Typed settings, loaded once from the environment (AGENTS.md section 3).

No other module reads ``os.environ``. Required settings that are missing fail at start-up with
the variable's name in the error.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process configuration. Every field has a matching, commented line in ``.env.example``."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(description="SQLAlchemy URL of the platform's own Postgres.")
    environment: str = Field(default="local", pattern="^(local|ci|staging|private)$")
    log_level: str = Field(default="INFO")


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, built on first use."""
    return Settings()  # type: ignore[call-arg]  # required fields come from the environment
