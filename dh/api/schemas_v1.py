from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

LaneLiteral = Literal["name", "authority"]
ReviewLiteral = Literal["ready", "research", "reject"]
JobKind = Literal[
    "inventory_scan",
    "content_crawl",
    "availability_refresh",
    "backlink_validate",
    "wayback_refresh",
    "recompute_assessments",
    "generate_dossier",
]


class LaneAssessmentItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    lane: LaneLiteral
    name_subtype: str | None
    state: str
    screen_passed: bool
    lane_score: float | None
    model_version: str
    config_version: int
    computed_at: dt.datetime
    signals: dict[str, Any] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)


class GateItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    lane: str
    gate_key: str
    state: Literal["pass", "fail", "pending"]
    fatal: bool
    details: str | None
    evidence_refs: list[str] = Field(default_factory=list)
    evaluated_at: dt.datetime


class DossierItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    lane: LaneLiteral
    status: str
    generated_at: dt.datetime
    thesis: str | None
    buyer_thesis: dict[str, Any] = Field(default_factory=dict)
    comparable_sales: list[dict[str, Any]] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    evidence_summary: dict[str, Any] = Field(default_factory=dict)


class CandidateSummaryV1(BaseModel):
    id: int
    domain: str
    lanes: list[LaneLiteral]
    hybrid: bool
    name_subtype: str | None
    name_score: float | None
    authority_score: float | None
    review_state: ReviewLiteral
    lifecycle_state: str
    current_status: str | None
    availability_confidence: str | None
    promoted_at: dt.datetime | None
    last_observed: dt.datetime
    dossier_updated_at: dt.datetime | None


class CandidatePageV1(BaseModel):
    items: list[CandidateSummaryV1]
    next_cursor: str | None = None


class LinkEvidenceItem(BaseModel):
    source_url: str
    source_domain: str
    target_url: str
    anchor_text: str | None
    context_text: str | None
    semantic_location: str | None
    rel_flags: list[str] = Field(default_factory=list)
    is_editorial: bool | None
    currently_live: bool | None
    last_seen: dt.datetime


class QuoteItem(BaseModel):
    registrar: str | None
    availability_status: str | None
    price_class: str | None
    quote_price_micros: int | None
    quote_currency: str
    observed_at: dt.datetime
    expires_at: dt.datetime | None


class ReviewItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    decision: ReviewLiteral
    reason: str | None
    notes: str | None
    decided_at: dt.datetime
    device_id: int | None


class CandidateDetailV1(CandidateSummaryV1):
    assessments: list[LaneAssessmentItem]
    gates: list[GateItem]
    dossiers: list[DossierItem]
    links: list[LinkEvidenceItem]
    quotes: list[QuoteItem]
    reviews: list[ReviewItem]


class TodayResponse(BaseModel):
    generated_at: dt.datetime
    system_health: Literal["healthy", "degraded"]
    unread_events: int
    most_urgent_domain: str | None
    candidates: list[CandidateSummaryV1]


class ReviewCreate(BaseModel):
    decision: ReviewLiteral
    reason: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=4000)


class EventItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    candidate_id: int | None
    event_type: str
    payload: dict[str, Any]
    created_at: dt.datetime
    config_version: int | None
    read: bool = False


class JobCreate(BaseModel):
    kind: JobKind
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=96)


class JobItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: JobKind
    state: Literal["queued", "running", "success", "partial", "failed"]
    payload: dict[str, Any]
    idempotency_key: str
    config_version: int
    created_at: dt.datetime
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    claimed_by: str | None
    result: dict[str, Any] | None
    error: str | None


class WorkerItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    worker_name: str
    state: str
    job_id: str | None
    observed_at: dt.datetime
    details: dict[str, Any] = Field(default_factory=dict)


class RunItemV1(BaseModel):
    id: str
    kind: Literal["discovery", "crawl"]
    source: str
    state: str
    started_at: dt.datetime
    finished_at: dt.datetime | None
    metrics: dict[str, Any] = Field(default_factory=dict)
    error: str | None


class ConfigCreate(BaseModel):
    config: dict[str, Any]
    notes: str | None = Field(default=None, max_length=2000)


class ConfigVersionItem(BaseModel):
    version: int
    created_at: dt.datetime
    parent_version: int | None
    config: dict[str, Any]
    notes: str | None
    is_active: bool
    activated_at: dt.datetime | None
    diff: dict[str, dict[str, Any]] = Field(default_factory=dict)


class PairingComplete(BaseModel):
    code: str = Field(min_length=12, max_length=128)
    device_name: str = Field(min_length=1, max_length=128)


class PairingResult(BaseModel):
    device_id: int
    device_name: str
    token: str


class DeviceItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_name: str
    created_at: dt.datetime
    last_seen_at: dt.datetime | None
    revoked_at: dt.datetime | None


class PortfolioOutcomeCreate(BaseModel):
    outcome: Literal["acquired", "lost", "inquiry", "sold", "renewed", "abandoned"]
    amount_micros: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    notes: str | None = Field(default=None, max_length=4000)


class PortfolioOutcomeItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    candidate_id: int
    outcome: str
    occurred_at: dt.datetime
    amount_micros: int | None
    currency: str | None
    notes: str | None
