"""SQLAlchemy 2 models — mirrors PRD §12 data model exactly.

All tables defined here. Alembic auto-generate operates against `metadata`.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    JSON,
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
    composite_score: Mapped[float | None] = mapped_column(Numeric)
    score_version: Mapped[int | None] = mapped_column(
        ForeignKey("scoring_weights.version", ondelete="SET NULL")
    )
    hard_filtered: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    hard_filter_reason: Mapped[str | None] = mapped_column(String(64))

    mentions: Mapped[list["SourceMention"]] = relationship(back_populates="candidate")

    __table_args__ = (
        Index(
            "ix_candidates_composite_score_not_filtered",
            "composite_score",
            postgresql_where=text("NOT hard_filtered"),
        ),
        Index("ix_candidates_current_status", "current_status"),
    )


class SourceMention(Base):
    __tablename__ = "source_mentions"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE")
    )
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
        UniqueConstraint("source_url_hash", "cited_url_hash"),
        Index("ix_source_mentions_candidate_context", "candidate_id", "context_type"),
        Index("ix_source_mentions_source_url_hash", "source_url_hash"),
        Index("ix_source_mentions_cited_url_hash", "cited_url_hash"),
    )


# --------------------------------------------------------------------------- #
# Evidence trail
# --------------------------------------------------------------------------- #

class RdapSnapshot(Base):
    __tablename__ = "rdap_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE")
    )
    observed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    rdap_server: Mapped[str | None] = mapped_column(Text)
    epp_statuses: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    expiry_date: Mapped[dt.date | None] = mapped_column(Date)
    registrar: Mapped[str | None] = mapped_column(Text)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("ix_rdap_snapshots_candidate_observed", "candidate_id", "observed_at"),
    )


class AvailabilityCheck(Base):
    __tablename__ = "availability_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE")
    )
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
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE")
    )
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
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE")
    )
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
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE")
    )
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
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE")
    )
    observed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    registrar: Mapped[str | None] = mapped_column(String(64))
    is_premium: Mapped[bool | None] = mapped_column(Boolean)
    quote_price_micros: Mapped[int | None] = mapped_column(BigInteger)
    renewal_price_micros: Mapped[int | None] = mapped_column(BigInteger)
    quote_currency: Mapped[str] = mapped_column(String(3), server_default=text("'USD'"))
    api_cost_micros: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("ix_registrar_quotes_candidate_observed", "candidate_id", "observed_at"),
    )


class Outcome(Base):
    __tablename__ = "outcomes"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE")
    )
    decided_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    decision: Mapped[str | None] = mapped_column(String(32))
    pass_reason: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)
    acquisition_cost_usd: Mapped[float | None] = mapped_column(Numeric)
    acquisition_channel: Mapped[str | None] = mapped_column(String(64))


__all__ = [
    "Base",
    "metadata",
    "Source",
    "SourceTerms",
    "Candidate",
    "SourceMention",
    "ScoringWeights",
    "RdapSnapshot",
    "AvailabilityCheck",
    "HttpObservation",
    "WaybackSnapshot",
    "ClassificationRun",
    "RegistrarQuote",
    "Outcome",
]
