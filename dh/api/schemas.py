"""Pydantic v2 schemas for the headless FastAPI surface."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CandidateListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    domain: str
    composite_score: float | None
    current_status: str | None
    availability_confidence: str | None
    open_pagerank: float | None
    referring_domains: int | None
    authority_rank: int | None
    authority_source: str | None
    score_version: int | None
    hard_filtered: bool
    hard_filter_reason: str | None
    score_breakdown: dict[str, Any] | None = None
    top_reasons: list[str] | None = None
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
    decision: Literal["bought", "passed", "watching", "needs_manual_review", "lost_to_other"]
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
    closes_at: dt.datetime | None = None
    verdict: str = "research"
    missing_evidence: list[str] = Field(default_factory=list)
    top_reasons: list[str] = Field(default_factory=list)


class MarketplaceEvidence(BaseModel):
    marketplace: str
    acquisition_type: str
    listing_status: str
    drop_date: dt.date | None
    closes_at: dt.datetime | None
    minimum_price_micros: int | None
    current_price_micros: int | None
    currency: str
    listing_url: str | None
    last_seen: dt.datetime


class OpportunityItem(BaseModel):
    candidate_id: int
    domain: str
    verdict: str
    overall_score: float
    authority_score: float
    resale_score: float
    risk_score: float
    confidence_score: float
    open_pagerank: float | None
    referring_domains: int | None
    authority_rank: int | None
    current_status: str | None
    availability_confidence: str | None
    reasons: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    signals: dict[str, Any] = Field(default_factory=dict)
    computed_at: dt.datetime
    latest_decision: str | None = None
    acquisition: MarketplaceEvidence | None = None
    wayback: WaybackEvidence | None = None


class DiscoveryRunItem(BaseModel):
    id: int
    source: str
    started_at: dt.datetime
    finished_at: dt.datetime | None
    status: str
    source_version: str | None
    fetched_count: int
    prefiltered_count: int
    matched_count: int
    persisted_count: int
    metrics: dict[str, Any] | None
    error: str | None


class PipelineStatus(BaseModel):
    last_run: DiscoveryRunItem | None
    active_acquisition_candidates: int
    research_queue: int
    observe_queue: int
    rejected: int
    manually_closed: int
    rdap_confirmation_pending: int
    wayback_review_pending: int
    automated_purchase_enabled: bool = False
    human_approval_required: bool = True
