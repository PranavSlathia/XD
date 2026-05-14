"""Typed settings loaded from environment / .env file."""
from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration. Validated at startup; fail fast on missing values."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="DH_",
        case_sensitive=False,
        extra="ignore",
    )

    # --- DB ---
    db_host: str = "dh-pg"
    db_port: int = 5432
    db_name: str = "dh"
    db_user: str = "dh"
    db_password: str = Field(default="changeme", min_length=4)

    # --- Redis ---
    redis_url: str = "redis://dh-redis:6379/0"

    # --- Runtime ---
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    env: Literal["dev", "prod"] = "dev"
    project_root: Path = Field(default_factory=lambda: Path.cwd())

    # --- Discord ---
    discord_webhook_url: str = ""

    # --- Spend caps ---
    llm_daily_call_cap: int = 200
    whoisjson_daily_cap: int = 33
    whoisfreaks_daily_cap: int = 15
    bigquery_max_bytes_billed: int = 10 * 1024**3  # 10 GB

    # --- LLM transport ---
    classifier_transport: Literal["codex_cli", "anthropic_api", "openai_api", "stub"] = "codex_cli"
    codex_bin: str = "codex"

    # --- BigQuery ---
    bigquery_project: str = ""

    # --- GitHub ---
    github_token: str = ""

    # --- WhoisJSON ---
    whoisjson_api_key: str = ""

    # --- Premium-ceiling for digest gate (USD) ---
    premium_ceiling_usd: int = 200

    # --- Derived properties ---

    @cached_property
    def db_url_async(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @cached_property
    def db_url_sync(self) -> str:
        # Used by Alembic offline migrations only.
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @cached_property
    def premium_ceiling_micros(self) -> int:
        return self.premium_ceiling_usd * 1_000_000


settings = Settings()
