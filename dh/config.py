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
    project_root: Path = Field(default_factory=Path.cwd)

    # --- Discord operator surface (Vulture) ---
    discord_webhook_url: str = ""
    discord_bot_token: str = ""
    discord_guild_id: int = 0
    discord_channel_id: int = 0
    discord_owner_id: int = 0
    discord_digest_hour_utc: int = 3
    discord_digest_minute_utc: int = 30

    # --- Spend caps ---
    llm_daily_call_cap: int = 200
    whoisjson_daily_cap: int = 33
    whoisfreaks_daily_cap: int = 15
    bigquery_max_bytes_billed: int = 10 * 1024**3  # 10 GB

    # --- LLM transport ---
    classifier_transport: Literal["codex_cli", "anthropic_api", "openai_api", "stub"] = "stub"
    codex_bin: str = "codex"
    classifier_enforce_hard_filters: bool = False

    # --- BigQuery ---
    bigquery_project: str = ""

    # --- GitHub ---
    github_token: str = ""

    # --- WhoisJSON ---
    whoisjson_api_key: str = ""

    # --- DomCop Open PageRank ---
    openpagerank_api_key: str = ""

    # --- Continuous expiring-inventory discovery ---
    inventory_data_dir: Path = Path("/var/data/dh")
    inventory_interval_hours: int = 6
    inventory_tlds: str = "com"
    inventory_min_opr: float = 2.5
    inventory_min_referring_domains: int = 10
    inventory_max_candidates: int = 500
    inventory_detail_limit: int = 150
    inventory_reference_refresh_days: int = 30
    namebio_retail_stats_refresh_hours: int = 24
    opportunity_research_threshold: float = 45.0
    opportunity_min_keyword_sales: int = 10

    # --- Porkbun registrar quote lookup ---
    porkbun_api_key: str = ""
    porkbun_secret_api_key: str = ""
    porkbun_daily_quote_cap: int = 50

    # --- Premium-ceiling for digest gate (USD) ---
    premium_ceiling_usd: int = 200

    # --- Authority floor (Open PageRank, 0-10) ---
    # Confirmed-available domains below this OPR are hard-filtered as
    # 'low_authority'. Encodes the dofollow-authority requirement: PageRank
    # doesn't flow through rel=nofollow, so OPR is a real authority signal.
    opr_min_authority: float = 3.0

    # --- Worker tunables ---
    a2_n_repos: int = 500
    a2_star_floor: int = 5000
    a2_pushed_before: str = ""
    a2_interval_hours: int = 24

    rdap_batch_size: int = 100
    rdap_interval_minutes: int = 10
    rdap_active_stale_hours: int = 12
    rdap_available_stale_hours: int = 24
    rdap_registered_stale_days: int = 30
    rdap_unknown_stale_days: int = 7

    wayback_batch_size: int = 50
    wayback_top_n: int = 200
    wayback_interval_minutes: int = 30

    scoring_batch_size: int = 200
    scoring_interval_seconds: int = 60

    registrar_batch_size: int = 10
    registrar_interval_minutes: int = 60

    # --- Sentry / GlitchTip ---
    sentry_dsn: str = ""

    # --- OpenTelemetry ---
    # Set to e.g. "http://tempo:4318" or "http://localhost:4318" to enable.
    # Leave empty for a console exporter only (dev-friendly, low overhead).
    otel_exporter_otlp_endpoint: str = ""
    otel_service_namespace: str = "domain-hunter"
    otel_console_exporter: bool = False
    otel_sample_rate: float = Field(default=0.05, ge=0.0, le=1.0)

    # --- Notifications ---
    digest_min_score: int = 70
    digest_max_items: int = 10

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
