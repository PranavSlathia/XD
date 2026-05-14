"""Pydantic v2 schemas for the FastAPI dashboard surface."""
from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CandidateListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    domain: str
    composite_score: float | None
    current_status: str | None
    availability_confidence: str | None
    score_version: int | None
    hard_filtered: bool
    hard_filter_reason: str | None
    first_observed: dt.datetime
    last_observed: dt.datetime


class MentionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_url: str | None
    cited_url: str | None
    context_type: str | None
    context_snippet: str | None
    observed_at: dt.datetime


class AvailabilityEvidence(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: str
    status: str | None
    is_authoritative: bool | None
    observed_at: dt.datetime
    cost_micros: int


class WaybackEvidence(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    first_capture: dt.date | None
    last_capture: dt.date | None
    capture_count: int | None
    observed_at: dt.datetime
    cdx_summary: dict[str, Any] | None


class CandidateDetail(CandidateListItem):
    mentions: list[MentionItem] = Field(default_factory=list)
    availability_history: list[AvailabilityEvidence] = Field(default_factory=list)
    wayback_history: list[WaybackEvidence] = Field(default_factory=list)


class DecisionCreate(BaseModel):
    domain: str
    decision: str  # 'bought'|'passed'|'watching'|'needs_manual_review'|'lost_to_other'
    pass_reason: str | None = None
    notes: str | None = None
    acquisition_cost_usd: float | None = None
    acquisition_channel: str | None = None


class DecisionResponse(BaseModel):
    id: int
    candidate_id: int
    decision: str | None
    decided_at: dt.datetime


class ScoringWeightsItem(BaseModel):
    version: int
    weights_json: dict[str, float]
    notes: str | None
    created_at: dt.datetime


class ScoringWeightsCreate(BaseModel):
    weights_json: dict[str, float]
    notes: str | None = None


class HealthResponse(BaseModel):
    ok: bool
    db: bool
    redis: bool


class CandidateDigestItem(BaseModel):
    domain: str
    composite_score: float | None = None
    current_status: str | None = None
    quote_price_micros: int | None = None
    top_reasons: list[str] = Field(default_factory=list)
