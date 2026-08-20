from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dh.db.models import EngineConfigVersion

CORE_TLDS = ("com", "net", "org", "co", "io", "ai")


class PaidEnrichmentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = "dataforseo"
    monthly_budget_micros: int = Field(default=25_000_000, ge=0, le=1_000_000_000)
    operation_reserve_micros: int = Field(default=100_000, ge=1_000, le=5_000_000)


class NameLaneConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    screen_min_score: float = Field(default=65.0, ge=0.0, le=100.0)
    inventory_candidate_limit: int = Field(default=1_000, ge=1, le=10_000)


class AuthorityLaneConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prefilter_min_referring_domains: int = Field(default=10, ge=1, le=1_000_000)
    ready_thresholds_enabled: bool = False


class CrawlerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concurrency: int = Field(default=2, ge=1, le=4)
    max_pages_per_seed: int = Field(default=25, ge=1, le=250)
    max_external_domains_per_page: int = Field(default=200, ge=1, le=1_000)
    max_response_bytes: int = Field(default=2_000_000, ge=100_000, le=10_000_000)
    request_timeout_seconds: float = Field(default=15.0, ge=2.0, le=60.0)
    minimum_delay_seconds: float = Field(default=1.0, ge=0.25, le=30.0)


class EngineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    core_tlds: tuple[str, ...] = CORE_TLDS
    paid_enrichment: PaidEnrichmentConfig = Field(default_factory=PaidEnrichmentConfig)
    name: NameLaneConfig = Field(default_factory=NameLaneConfig)
    authority: AuthorityLaneConfig = Field(default_factory=AuthorityLaneConfig)
    crawler: CrawlerConfig = Field(default_factory=CrawlerConfig)

    @model_validator(mode="after")
    def validate_tlds(self) -> EngineConfig:
        normalized = tuple(dict.fromkeys(item.lower().lstrip(".") for item in self.core_tlds))
        if not normalized or any(item not in CORE_TLDS for item in normalized):
            raise ValueError("core_tlds must be a non-empty subset of the approved core six")
        self.core_tlds = normalized
        return self


DEFAULT_ENGINE_CONFIG = EngineConfig()


async def get_active_config(
    session: AsyncSession,
) -> tuple[EngineConfigVersion, EngineConfig]:
    row = (
        await session.execute(
            select(EngineConfigVersion)
            .where(EngineConfigVersion.is_active.is_(True))
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise RuntimeError("no active engine configuration")
    return row, EngineConfig.model_validate(row.config_json)


def config_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return a stable dotted-path diff suitable for the native settings preview."""

    changes: dict[str, dict[str, Any]] = {}

    def walk(left: object, right: object, path: str) -> None:
        if isinstance(left, dict) and isinstance(right, dict):
            left_map = cast(dict[str, object], left)
            right_map = cast(dict[str, object], right)
            for key in sorted(set(left_map) | set(right_map)):
                child = f"{path}.{key}" if path else str(key)
                walk(left_map.get(key), right_map.get(key), child)
            return
        if left != right:
            changes[path] = {"before": left, "after": right}

    walk(before, after, "")
    return changes
