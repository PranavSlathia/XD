"""SQLAlchemy 2 models — mirrors PRD §12 data model exactly.

All tables defined here. Alembic auto-generate operates against `metadata`.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# --------------------------------------------------------------------------- #
# Naming conventions for stable migration names
# --------------------------------------------------------------------------- #

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    metadata = metadata


# --------------------------------------------------------------------------- #
# Sources & provenance
# --------------------------------------------------------------------------- #


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    source_uri: Mapped[str] = mapped_column(Text, nullable=False)
    authority: Mapped[float | None] = mapped_column(Numeric)
    first_seen: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("kind", "source_uri"),)


class SourceTerms(Base):
    """Per-source legal / ToS / robots memory."""

    __tablename__ = "source_terms"

    kind: Mapped[str] = mapped_column(String(64), primary_key=True)
    license: Mapped[str | None] = mapped_column(String(64))
    redistribution_allowed: Mapped[bool | None] = mapped_column(Boolean)
    attribution_required: Mapped[bool | None] = mapped_column(Boolean)
    rate_limit_notes: Mapped[str | None] = mapped_column(Text)
    robots_policy: Mapped[str | None] = mapped_column(Text)
    terms_url: Mapped[str | None] = mapped_column(Text)
    last_verified_at: Mapped[dt.date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)


# --------------------------------------------------------------------------- #
# Candidates
# --------------------------------------------------------------------------- #


class ScoringWeights(Base):
    __tablename__ = "scoring_weights"

    version: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    weights_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(253), unique=True, nullable=False)
    first_observed: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_observed: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    current_status: Mapped[str | None] = mapped_column(String(32))
    availability_confidence: Mapped[str | None] = mapped_column(String(16))
    # Backlink-authority enrichments (written at ingest, consumed by scoring).
    # NULL until enriched.
    open_pagerank: Mapped[float | None] = mapped_column(Numeric)  # 0-10 (DomCop OPR)
    referring_domains: Mapped[int | None] = mapped_column(Integer)  # Phase 2 (Common Crawl)
    authority_rank: Mapped[int | None] = mapped_column(Integer)
    authority_source: Mapped[str | None] = mapped_column(String(64))
    authority_observed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    composite_score: Mapped[float | None] = mapped_column(Numeric)
    score_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    top_reasons: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    score_version: Mapped[int | None] = mapped_column(
        ForeignKey("scoring_weights.version", ondelete="SET NULL")
    )
    hard_filtered: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    hard_filter_reason: Mapped[str | None] = mapped_column(String(64))
    # XD v1 keeps lifecycle, promotion, and operator review independent.  The
    # legacy ``current_status`` column remains as an evidence denormalization
    # for old workers and API clients.
    lifecycle_state: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'observed'")
    )
    review_state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'research'")
    )
    promoted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    dossier_updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    mentions: Mapped[list[SourceMention]] = relationship(back_populates="candidate")
    marketplace_listings: Mapped[list[MarketplaceListing]] = relationship(
        back_populates="candidate"
    )

    __table_args__ = (
        Index(
            "ix_candidates_composite_score_not_filtered",
            "composite_score",
            postgresql_where=text("NOT hard_filtered"),
        ),
        Index("ix_candidates_current_status", "current_status"),
        Index(
            "ix_candidates_xd_review_dossier",
            "review_state",
            "dossier_updated_at",
            postgresql_where=text("promoted_at IS NOT NULL"),
        ),
    )


class SourceMention(Base):
    __tablename__ = "source_mentions"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"))

    source_url: Mapped[str | None] = mapped_column(Text)
    source_url_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))

    cited_url: Mapped[str | None] = mapped_column(Text)
    cited_url_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))

    context_type: Mapped[str | None] = mapped_column(String(32))
    context_snippet: Mapped[str | None] = mapped_column(Text)

    observed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    candidate: Mapped[Candidate] = relationship(back_populates="mentions")

    __table_args__ = (
        UniqueConstraint(
            "source_url_hash",
            "cited_url_hash",
            name="uq_source_mentions_source_cited_hashes",
        ),
        Index("ix_source_mentions_candidate_context", "candidate_id", "context_type"),
        Index("ix_source_mentions_source_url_hash", "source_url_hash"),
        Index("ix_source_mentions_cited_url_hash", "cited_url_hash"),
    )


# --------------------------------------------------------------------------- #
# Continuous marketplace discovery
# --------------------------------------------------------------------------- #


class DiscoveryRun(Base):
    """One source-ingestion attempt and its funnel counts."""

    __tablename__ = "discovery_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'running'")
    )
    source_version: Mapped[str | None] = mapped_column(String(128))
    fetched_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    prefiltered_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    matched_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    persisted_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_discovery_runs_source_started", "source", "started_at"),)


class MarketplaceListing(Base):
    """Read-only evidence that a domain has a real acquisition path."""

    __tablename__ = "marketplace_listings"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    marketplace: Mapped[str] = mapped_column(String(64), nullable=False)
    external_key: Mapped[str] = mapped_column(String(255), nullable=False)
    acquisition_type: Mapped[str] = mapped_column(String(32), nullable=False)
    listing_status: Mapped[str] = mapped_column(String(32), nullable=False)
    drop_date: Mapped[dt.date | None] = mapped_column(Date)
    closes_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    minimum_price_micros: Mapped[int | None] = mapped_column(BigInteger)
    current_price_micros: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), server_default=text("'USD'"))
    listing_url: Mapped[str | None] = mapped_column(Text)
    first_seen: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    candidate: Mapped[Candidate] = relationship(back_populates="marketplace_listings")

    __table_args__ = (
        UniqueConstraint("marketplace", "external_key"),
        Index(
            "ix_marketplace_listings_active_deadline",
            "listing_status",
            "closes_at",
        ),
        Index(
            "ix_marketplace_listings_candidate_seen",
            "candidate_id",
            "last_seen",
        ),
    )


class OpportunityAssessment(Base):
    """Versioned deterministic research verdict; never an instruction to buy."""

    __tablename__ = "opportunity_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    computed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    authority_score: Mapped[float] = mapped_column(Numeric, nullable=False)
    resale_score: Mapped[float] = mapped_column(Numeric, nullable=False)
    risk_score: Mapped[float] = mapped_column(Numeric, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Numeric, nullable=False)
    overall_score: Mapped[float] = mapped_column(Numeric, nullable=False)
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    reasons: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    rejection_reasons: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    missing_evidence: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    signals: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (
        UniqueConstraint("candidate_id", "model_version"),
        Index(
            "ix_opportunity_assessments_verdict_score",
            "verdict",
            "overall_score",
        ),
    )


# --------------------------------------------------------------------------- #
# Evidence trail
# --------------------------------------------------------------------------- #


class RdapSnapshot(Base):
    __tablename__ = "rdap_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    observed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    rdap_server: Mapped[str | None] = mapped_column(Text)
    epp_statuses: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    expiry_date: Mapped[dt.date | None] = mapped_column(Date)
    registrar: Mapped[str | None] = mapped_column(Text)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (Index("ix_rdap_snapshots_candidate_observed", "candidate_id", "observed_at"),)


class AvailabilityCheck(Base):
    __tablename__ = "availability_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    observed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    source: Mapped[str] = mapped_column(String(32))
    status: Mapped[str | None] = mapped_column(String(32))
    is_authoritative: Mapped[bool | None] = mapped_column(Boolean)
    cost_micros: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (
        Index(
            "ix_availability_checks_candidate_observed",
            "candidate_id",
            "observed_at",
        ),
    )


class HttpObservation(Base):
    __tablename__ = "http_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    observed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    status_code: Mapped[int | None] = mapped_column(Integer)
    final_url: Mapped[str | None] = mapped_column(Text)
    is_parked: Mapped[bool | None] = mapped_column(Boolean)
    ns_signal: Mapped[str | None] = mapped_column(String(64))


class WaybackSnapshot(Base):
    __tablename__ = "wayback_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    observed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    first_capture: Mapped[dt.date | None] = mapped_column(Date)
    last_capture: Mapped[dt.date | None] = mapped_column(Date)
    capture_count: Mapped[int | None] = mapped_column(Integer)
    cdx_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ClassificationRun(Base):
    __tablename__ = "classification_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    observed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_used: Mapped[str] = mapped_column(String(128), nullable=False)
    classifier_version: Mapped[str | None] = mapped_column(String(64))
    snapshot_ids: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    classification: Mapped[str | None] = mapped_column(String(32))
    confidence: Mapped[float | None] = mapped_column(Numeric)
    cost_micros: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("ix_classification_runs_cache_key", "cache_key"),
        Index(
            "ix_classification_runs_candidate_observed",
            "candidate_id",
            "observed_at",
        ),
    )


class RegistrarQuote(Base):
    __tablename__ = "registrar_quotes"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    observed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    registrar: Mapped[str | None] = mapped_column(String(64))
    is_premium: Mapped[bool | None] = mapped_column(Boolean)
    quote_price_micros: Mapped[int | None] = mapped_column(BigInteger)
    renewal_price_micros: Mapped[int | None] = mapped_column(BigInteger)
    quote_currency: Mapped[str] = mapped_column(String(3), server_default=text("'USD'"))
    api_cost_micros: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    availability_status: Mapped[str | None] = mapped_column(String(32))
    price_class: Mapped[str | None] = mapped_column(String(16))
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("ix_registrar_quotes_candidate_observed", "candidate_id", "observed_at"),
    )


class Outcome(Base):
    __tablename__ = "outcomes"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    decided_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    decision: Mapped[str | None] = mapped_column(String(32))
    pass_reason: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)
    acquisition_cost_usd: Mapped[float | None] = mapped_column(Numeric)
    acquisition_channel: Mapped[str | None] = mapped_column(String(64))


# --------------------------------------------------------------------------- #
# XD v1: independent lanes, gates, dossiers, crawl evidence, and operator state
# --------------------------------------------------------------------------- #


class EngineConfigVersion(Base):
    """Immutable engine configuration; exactly one version is active."""

    __tablename__ = "engine_config_versions"

    version: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_by_device_id: Mapped[int | None] = mapped_column(
        ForeignKey("device_credentials.id", ondelete="SET NULL")
    )
    parent_version: Mapped[int | None] = mapped_column(
        ForeignKey("engine_config_versions.version", ondelete="SET NULL")
    )
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    activated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "uq_engine_config_versions_single_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )


class LaneAssessment(Base):
    """Independent Name or Authority judgement; scores never cross lanes."""

    __tablename__ = "lane_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    lane: Mapped[str] = mapped_column(String(16), nullable=False)
    name_subtype: Mapped[str | None] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    screen_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    lane_score: Mapped[float | None] = mapped_column(Numeric)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    config_version: Mapped[int] = mapped_column(
        ForeignKey("engine_config_versions.version"), nullable=False
    )
    computed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    signals: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reasons: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    missing_evidence: Mapped[list[str] | None] = mapped_column(ARRAY(String))

    __table_args__ = (
        UniqueConstraint("candidate_id", "lane", "config_version"),
        Index("ix_lane_assessments_lane_state", "lane", "state", "computed_at"),
        Index(
            "ix_lane_assessments_config_lane_state_candidate",
            "config_version",
            "lane",
            "state",
            "candidate_id",
        ),
    )


class GateResult(Base):
    """Versioned hard-gate result. Missing evidence is always ``pending``."""

    __tablename__ = "gate_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    lane: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'shared'"))
    gate_key: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    fatal: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    config_version: Mapped[int] = mapped_column(
        ForeignKey("engine_config_versions.version"), nullable=False
    )
    evaluated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    details: Mapped[str | None] = mapped_column(Text)
    evidence_refs: Mapped[list[str] | None] = mapped_column(ARRAY(String))

    __table_args__ = (
        UniqueConstraint("candidate_id", "lane", "gate_key", "config_version"),
        Index("ix_gate_results_candidate_state", "candidate_id", "state"),
    )


class CandidateDossier(Base):
    __tablename__ = "candidate_dossiers"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    lane: Mapped[str] = mapped_column(String(16), nullable=False)
    config_version: Mapped[int] = mapped_column(
        ForeignKey("engine_config_versions.version"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    generated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    thesis: Mapped[str | None] = mapped_column(Text)
    buyer_thesis: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    comparable_sales: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    risks: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    evidence_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (UniqueConstraint("candidate_id", "lane", "config_version"),)


class CrawlSeed(Base):
    __tablename__ = "crawl_seeds"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    allowed_host: Mapped[str] = mapped_column(String(253), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    terms_verified_at: Mapped[dt.date | None] = mapped_column(Date)
    max_pages: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("25"))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    seed_id: Mapped[int] = mapped_column(ForeignKey("crawl_seeds.id", ondelete="CASCADE"))
    operator_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("operator_jobs.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    pages_fetched: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    links_observed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class SourcePage(Base):
    __tablename__ = "source_pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    seed_id: Mapped[int | None] = mapped_column(ForeignKey("crawl_seeds.id", ondelete="SET NULL"))
    url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    host: Mapped[str] = mapped_column(String(253), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    topic: Mapped[str | None] = mapped_column(String(128))
    quality_score: Mapped[float | None] = mapped_column(Numeric)
    title: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(128))
    etag: Mapped[str | None] = mapped_column(Text)
    outgoing_urls: Mapped[list[str] | None] = mapped_column(JSONB)
    content_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    first_seen: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class LinkObservation(Base):
    __tablename__ = "link_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_page_id: Mapped[int] = mapped_column(
        ForeignKey("source_pages.id", ondelete="CASCADE")
    )
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL")
    )
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    target_url_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    target_domain: Mapped[str] = mapped_column(String(253), nullable=False)
    anchor_text: Mapped[str | None] = mapped_column(Text)
    context_text: Mapped[str | None] = mapped_column(Text)
    semantic_location: Mapped[str | None] = mapped_column(String(32))
    rel_flags: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    is_editorial: Mapped[bool | None] = mapped_column(Boolean)
    is_sitewide: Mapped[bool | None] = mapped_column(Boolean)
    target_http_status: Mapped[int | None] = mapped_column(Integer)
    currently_live: Mapped[bool | None] = mapped_column(Boolean)
    first_seen: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("source_page_id", "target_url_hash"),
        Index("ix_link_observations_target_domain", "target_domain", "last_seen"),
    )


class DeviceCredential(Base):
    __tablename__ = "device_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_name: Mapped[str] = mapped_column(String(128), nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class PairingCode(Base):
    __tablename__ = "pairing_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code_hash: Mapped[bytes] = mapped_column(LargeBinary(64), unique=True, nullable=False)
    salt: Mapped[bytes] = mapped_column(LargeBinary(16), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class OperatorJob(Base):
    __tablename__ = "operator_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    active_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    created_by_device_id: Mapped[int | None] = mapped_column(
        ForeignKey("device_credentials.id", ondelete="SET NULL")
    )
    config_version: Mapped[int] = mapped_column(
        ForeignKey("engine_config_versions.version"), nullable=False
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_by: Mapped[str | None] = mapped_column(String(128))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_operator_jobs_state_created", "state", "created_at"),)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    worker_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("operator_jobs.id", ondelete="SET NULL"))
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    observed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class CandidateEvent(Base):
    __tablename__ = "candidate_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    config_version: Mapped[int | None] = mapped_column(
        ForeignKey("engine_config_versions.version", ondelete="SET NULL")
    )
    actor_device_id: Mapped[int | None] = mapped_column(
        ForeignKey("device_credentials.id", ondelete="SET NULL")
    )

    __table_args__ = (Index("ix_candidate_events_created", "id", "created_at"),)


class EventReadReceipt(Base):
    """One receipt per event makes read state global across both Macs."""

    __tablename__ = "event_read_receipts"

    event_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_events.id", ondelete="CASCADE"), primary_key=True
    )
    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("device_credentials.id", ondelete="SET NULL")
    )
    read_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CandidateReview(Base):
    __tablename__ = "candidate_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("device_credentials.id", ondelete="SET NULL")
    )
    reopens_review_id: Mapped[int | None] = mapped_column(
        ForeignKey("candidate_reviews.id", ondelete="SET NULL")
    )

    __table_args__ = (Index("ix_candidate_reviews_candidate_decided", "candidate_id", "decided_at"),)


class PortfolioOutcome(Base):
    __tablename__ = "portfolio_outcomes"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    amount_micros: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    notes: Mapped[str | None] = mapped_column(Text)


class ProviderUsage(Base):
    __tablename__ = "provider_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    cost_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL")
    )
    request_id: Mapped[str | None] = mapped_column(String(128))

    __table_args__ = (Index("ix_provider_usage_provider_occurred", "provider", "occurred_at"),)


__all__ = [
    "AvailabilityCheck",
    "Base",
    "Candidate",
    "CandidateDossier",
    "CandidateEvent",
    "CandidateReview",
    "ClassificationRun",
    "CrawlRun",
    "CrawlSeed",
    "DeviceCredential",
    "DiscoveryRun",
    "EngineConfigVersion",
    "EventReadReceipt",
    "GateResult",
    "HttpObservation",
    "LaneAssessment",
    "LinkObservation",
    "MarketplaceListing",
    "OperatorJob",
    "OpportunityAssessment",
    "Outcome",
    "PairingCode",
    "PortfolioOutcome",
    "ProviderUsage",
    "RdapSnapshot",
    "RegistrarQuote",
    "ScoringWeights",
    "Source",
    "SourceMention",
    "SourcePage",
    "SourceTerms",
    "WaybackSnapshot",
    "WorkerHeartbeat",
    "metadata",
]
