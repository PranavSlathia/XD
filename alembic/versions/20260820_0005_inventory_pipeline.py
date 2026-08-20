"""Add continuous marketplace discovery and opportunity evidence.

Revision ID: 0005_inventory_pipeline
Revises: 0004_score_explanations
Create Date: 2026-08-20
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_inventory_pipeline"
down_revision: str | None = "0004_score_explanations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("candidates", sa.Column("authority_rank", sa.Integer(), nullable=True))
    op.add_column("candidates", sa.Column("authority_source", sa.String(64), nullable=True))
    op.add_column(
        "candidates",
        sa.Column("authority_observed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "discovery_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status", sa.String(32), server_default=sa.text("'running'"), nullable=False
        ),
        sa.Column("source_version", sa.String(128), nullable=True),
        sa.Column("fetched_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("prefiltered_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("matched_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("persisted_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discovery_runs")),
    )
    op.create_index(
        "ix_discovery_runs_source_started",
        "discovery_runs",
        ["source", "started_at"],
    )

    op.create_table(
        "marketplace_listings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("marketplace", sa.String(64), nullable=False),
        sa.Column("external_key", sa.String(255), nullable=False),
        sa.Column("acquisition_type", sa.String(32), nullable=False),
        sa.Column("listing_status", sa.String(32), nullable=False),
        sa.Column("drop_date", sa.Date(), nullable=True),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("minimum_price_micros", sa.BigInteger(), nullable=True),
        sa.Column("current_price_micros", sa.BigInteger(), nullable=True),
        sa.Column(
            "currency", sa.String(3), server_default=sa.text("'USD'"), nullable=False
        ),
        sa.Column("listing_url", sa.Text(), nullable=True),
        sa.Column(
            "first_seen",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("raw_response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            name=op.f("fk_marketplace_listings_candidate_id_candidates"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_marketplace_listings")),
        sa.UniqueConstraint(
            "marketplace",
            "external_key",
            name=op.f("uq_marketplace_listings_marketplace_external_key"),
        ),
    )
    op.create_index(
        "ix_marketplace_listings_active_deadline",
        "marketplace_listings",
        ["listing_status", "closes_at"],
    )
    op.create_index(
        "ix_marketplace_listings_candidate_seen",
        "marketplace_listings",
        ["candidate_id", "last_seen"],
    )

    op.create_table(
        "opportunity_assessments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.String(32), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("authority_score", sa.Numeric(), nullable=False),
        sa.Column("resale_score", sa.Numeric(), nullable=False),
        sa.Column("risk_score", sa.Numeric(), nullable=False),
        sa.Column("confidence_score", sa.Numeric(), nullable=False),
        sa.Column("overall_score", sa.Numeric(), nullable=False),
        sa.Column("verdict", sa.String(32), nullable=False),
        sa.Column("reasons", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("rejection_reasons", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("missing_evidence", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("signals", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            name=op.f("fk_opportunity_assessments_candidate_id_candidates"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_opportunity_assessments")),
        sa.UniqueConstraint(
            "candidate_id",
            "model_version",
            name=op.f("uq_opportunity_assessments_candidate_id_model_version"),
        ),
    )
    op.create_index(
        "ix_opportunity_assessments_verdict_score",
        "opportunity_assessments",
        ["verdict", "overall_score"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_opportunity_assessments_verdict_score",
        table_name="opportunity_assessments",
    )
    op.drop_table("opportunity_assessments")
    op.drop_index(
        "ix_marketplace_listings_candidate_seen",
        table_name="marketplace_listings",
    )
    op.drop_index(
        "ix_marketplace_listings_active_deadline",
        table_name="marketplace_listings",
    )
    op.drop_table("marketplace_listings")
    op.drop_index("ix_discovery_runs_source_started", table_name="discovery_runs")
    op.drop_table("discovery_runs")
    op.drop_column("candidates", "authority_observed_at")
    op.drop_column("candidates", "authority_source")
    op.drop_column("candidates", "authority_rank")
