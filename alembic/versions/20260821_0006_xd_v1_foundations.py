"""Add XD v1 lanes, gates, jobs, events, crawl evidence, and device auth.

Revision ID: 0006_xd_v1_foundations
Revises: 0005_inventory_pipeline
Create Date: 2026-08-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_xd_v1_foundations"
down_revision: str | None = "0005_inventory_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidates",
        sa.Column(
            "lifecycle_state",
            sa.String(32),
            server_default=sa.text("'observed'"),
            nullable=False,
        ),
    )
    op.add_column(
        "candidates",
        sa.Column(
            "review_state",
            sa.String(16),
            server_default=sa.text("'research'"),
            nullable=False,
        ),
    )
    op.add_column("candidates", sa.Column("promoted_at", sa.DateTime(timezone=True)))
    op.add_column("candidates", sa.Column("dossier_updated_at", sa.DateTime(timezone=True)))
    op.create_index(
        "ix_candidates_xd_review_dossier",
        "candidates",
        ["review_state", "dossier_updated_at"],
        postgresql_where=sa.text("promoted_at IS NOT NULL"),
    )

    op.add_column("registrar_quotes", sa.Column("availability_status", sa.String(32)))
    op.add_column("registrar_quotes", sa.Column("price_class", sa.String(16)))
    op.add_column("registrar_quotes", sa.Column("expires_at", sa.DateTime(timezone=True)))

    op.create_table(
        "device_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_name", sa.String(128), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(32), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "pairing_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code_hash", sa.LargeBinary(64), nullable=False, unique=True),
        sa.Column("salt", sa.LargeBinary(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "engine_config_versions",
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by_device_id", sa.Integer()),
        sa.Column("parent_version", sa.Integer()),
        sa.Column("config_json", postgresql.JSONB(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["created_by_device_id"], ["device_credentials.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["parent_version"], ["engine_config_versions.version"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "uq_engine_config_versions_single_active",
        "engine_config_versions",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO engine_config_versions
                (version, config_json, notes, is_active, activated_at)
            VALUES
                (1, CAST(:config AS jsonb), :notes, true, now())
            """
        ).bindparams(
            config='{"schema_version":1,"core_tlds":["com","net","org","co","io","ai"],'
            '"paid_enrichment":{"provider":"dataforseo","monthly_budget_micros":25000000,'
            '"operation_reserve_micros":100000},'
            '"name":{"screen_min_score":65,"inventory_candidate_limit":1000},'
            '"authority":{"prefilter_min_referring_domains":10,'
            '"ready_thresholds_enabled":false},'
            '"crawler":{"concurrency":2,"max_pages_per_seed":25,'
            '"max_external_domains_per_page":200,"max_response_bytes":2000000,'
            '"request_timeout_seconds":15,"minimum_delay_seconds":1}}',
            notes="XD v1 safe defaults",
        )
    )

    op.create_table(
        "operator_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("active_key", sa.String(128), unique=True),
        sa.Column("created_by_device_id", sa.Integer()),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("claimed_by", sa.String(128)),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("error", sa.Text()),
        sa.ForeignKeyConstraint(
            ["created_by_device_id"], ["device_credentials.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["config_version"], ["engine_config_versions.version"]),
    )
    op.create_index("ix_operator_jobs_state_created", "operator_jobs", ["state", "created_at"])
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_name", sa.String(128), primary_key=True),
        sa.Column("job_id", sa.String(36)),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column(
            "observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("details", postgresql.JSONB()),
        sa.ForeignKeyConstraint(["job_id"], ["operator_jobs.id"], ondelete="SET NULL"),
    )

    op.create_table(
        "crawl_seeds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("url", sa.Text(), nullable=False, unique=True),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("allowed_host", sa.String(253), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("terms_verified_at", sa.Date()),
        sa.Column("max_pages", sa.Integer(), server_default=sa.text("25"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("seed_id", sa.Integer(), nullable=False),
        sa.Column("operator_job_id", sa.String(36)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("pages_fetched", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("links_observed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("metrics", postgresql.JSONB()),
        sa.ForeignKeyConstraint(["seed_id"], ["crawl_seeds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["operator_job_id"], ["operator_jobs.id"], ondelete="SET NULL"
        ),
    )
    op.create_table(
        "source_pages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("seed_id", sa.Integer()),
        sa.Column("url", sa.Text(), nullable=False, unique=True),
        sa.Column("host", sa.String(253), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("topic", sa.String(128)),
        sa.Column("quality_score", sa.Numeric()),
        sa.Column("title", sa.Text()),
        sa.Column("http_status", sa.Integer()),
        sa.Column("content_type", sa.String(128)),
        sa.Column("etag", sa.Text()),
        sa.Column("outgoing_urls", postgresql.JSONB()),
        sa.Column("content_hash", sa.LargeBinary(32)),
        sa.Column(
            "first_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "last_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["seed_id"], ["crawl_seeds.id"], ondelete="SET NULL"),
    )
    op.create_table(
        "link_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_page_id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer()),
        sa.Column("target_url", sa.Text(), nullable=False),
        sa.Column("target_url_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("target_domain", sa.String(253), nullable=False),
        sa.Column("anchor_text", sa.Text()),
        sa.Column("context_text", sa.Text()),
        sa.Column("semantic_location", sa.String(32)),
        sa.Column("rel_flags", postgresql.ARRAY(sa.String())),
        sa.Column("is_editorial", sa.Boolean()),
        sa.Column("is_sitewide", sa.Boolean()),
        sa.Column("target_http_status", sa.Integer()),
        sa.Column("currently_live", sa.Boolean()),
        sa.Column(
            "first_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "last_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["source_page_id"], ["source_pages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("source_page_id", "target_url_hash"),
    )
    op.create_index(
        "ix_link_observations_target_domain",
        "link_observations",
        ["target_domain", "last_seen"],
    )

    op.create_table(
        "lane_assessments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("lane", sa.String(16), nullable=False),
        sa.Column("name_subtype", sa.String(32)),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("screen_passed", sa.Boolean(), nullable=False),
        sa.Column("lane_score", sa.Numeric()),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("signals", postgresql.JSONB()),
        sa.Column("reasons", postgresql.ARRAY(sa.String())),
        sa.Column("missing_evidence", postgresql.ARRAY(sa.String())),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["config_version"], ["engine_config_versions.version"]),
        sa.UniqueConstraint("candidate_id", "lane", "config_version"),
    )
    op.create_index(
        "ix_lane_assessments_lane_state",
        "lane_assessments",
        ["lane", "state", "computed_at"],
    )
    op.create_index(
        "ix_lane_assessments_config_lane_state_candidate",
        "lane_assessments",
        ["config_version", "lane", "state", "candidate_id"],
    )
    op.create_table(
        "gate_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("lane", sa.String(16), server_default=sa.text("'shared'"), nullable=False),
        sa.Column("gate_key", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("fatal", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column(
            "evaluated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("details", sa.Text()),
        sa.Column("evidence_refs", postgresql.ARRAY(sa.String())),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["config_version"], ["engine_config_versions.version"]),
        sa.UniqueConstraint("candidate_id", "lane", "gate_key", "config_version"),
    )
    op.create_index(
        "ix_gate_results_candidate_state", "gate_results", ["candidate_id", "state"]
    )
    op.create_table(
        "candidate_dossiers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("lane", sa.String(16), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("thesis", sa.Text()),
        sa.Column("buyer_thesis", postgresql.JSONB()),
        sa.Column("comparable_sales", postgresql.JSONB()),
        sa.Column("risks", postgresql.ARRAY(sa.String())),
        sa.Column("evidence_summary", postgresql.JSONB()),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["config_version"], ["engine_config_versions.version"]),
        sa.UniqueConstraint("candidate_id", "lane", "config_version"),
    )

    op.create_table(
        "candidate_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("candidate_id", sa.Integer()),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("config_version", sa.Integer()),
        sa.Column("actor_device_id", sa.Integer()),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["config_version"], ["engine_config_versions.version"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["actor_device_id"], ["device_credentials.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_candidate_events_created", "candidate_events", ["id", "created_at"])
    op.create_table(
        "event_read_receipts",
        sa.Column("event_id", sa.BigInteger(), primary_key=True),
        sa.Column("device_id", sa.Integer()),
        sa.Column(
            "read_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["event_id"], ["candidate_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["device_credentials.id"], ondelete="SET NULL"),
    )
    op.create_table(
        "candidate_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(128)),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("device_id", sa.Integer()),
        sa.Column("reopens_review_id", sa.Integer()),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["device_credentials.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["reopens_review_id"], ["candidate_reviews.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_candidate_reviews_candidate_decided",
        "candidate_reviews",
        ["candidate_id", "decided_at"],
    )
    op.create_table(
        "portfolio_outcomes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("amount_micros", sa.BigInteger()),
        sa.Column("currency", sa.String(3)),
        sa.Column("notes", sa.Text()),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "provider_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("cost_micros", sa.BigInteger(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("candidate_id", sa.Integer()),
        sa.Column("request_id", sa.String(128)),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_provider_usage_provider_occurred",
        "provider_usage",
        ["provider", "occurred_at"],
    )


def downgrade() -> None:
    for table in (
        "provider_usage",
        "portfolio_outcomes",
        "candidate_reviews",
        "event_read_receipts",
        "candidate_events",
        "candidate_dossiers",
        "gate_results",
        "lane_assessments",
        "link_observations",
        "source_pages",
        "crawl_runs",
        "crawl_seeds",
        "worker_heartbeats",
        "operator_jobs",
        "engine_config_versions",
        "pairing_codes",
        "device_credentials",
    ):
        op.drop_table(table)
    op.drop_column("registrar_quotes", "expires_at")
    op.drop_column("registrar_quotes", "price_class")
    op.drop_column("registrar_quotes", "availability_status")
    op.drop_index("ix_candidates_xd_review_dossier", table_name="candidates")
    op.drop_column("candidates", "dossier_updated_at")
    op.drop_column("candidates", "promoted_at")
    op.drop_column("candidates", "review_state")
    op.drop_column("candidates", "lifecycle_state")
