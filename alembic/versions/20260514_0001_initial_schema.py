"""initial schema (PRD §12)

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-14
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision: str | None = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgvector for later Phase-4 embeddings; harmless if not used yet.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- sources ---
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("source_uri", sa.Text, nullable=False),
        sa.Column("authority", sa.Numeric),
        sa.Column(
            "first_seen",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("kind", "source_uri", name="uq_sources_kind_source_uri"),
    )

    # --- source_terms ---
    op.create_table(
        "source_terms",
        sa.Column("kind", sa.String(64), primary_key=True),
        sa.Column("license", sa.String(64)),
        sa.Column("redistribution_allowed", sa.Boolean),
        sa.Column("attribution_required", sa.Boolean),
        sa.Column("rate_limit_notes", sa.Text),
        sa.Column("robots_policy", sa.Text),
        sa.Column("terms_url", sa.Text),
        sa.Column("last_verified_at", sa.Date),
        sa.Column("notes", sa.Text),
    )

    # --- scoring_weights ---
    op.create_table(
        "scoring_weights",
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("weights_json", postgresql.JSONB, nullable=False),
        sa.Column("notes", sa.Text),
    )

    # --- candidates ---
    op.create_table(
        "candidates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("domain", sa.String(253), nullable=False, unique=True),
        sa.Column(
            "first_observed",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_observed",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("current_status", sa.String(32)),
        sa.Column("availability_confidence", sa.String(16)),
        sa.Column("composite_score", sa.Numeric),
        sa.Column(
            "score_version",
            sa.Integer,
            sa.ForeignKey("scoring_weights.version", ondelete="SET NULL"),
        ),
        sa.Column(
            "hard_filtered",
            sa.Boolean,
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("hard_filter_reason", sa.String(64)),
    )
    op.create_index(
        "ix_candidates_composite_score_not_filtered",
        "candidates",
        ["composite_score"],
        postgresql_where=sa.text("NOT hard_filtered"),
    )
    op.create_index("ix_candidates_current_status", "candidates", ["current_status"])

    # --- source_mentions ---
    op.create_table(
        "source_mentions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Integer,
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("sources.id")),
        sa.Column("source_url", sa.Text),
        sa.Column("source_url_hash", sa.LargeBinary(32)),
        sa.Column("cited_url", sa.Text),
        sa.Column("cited_url_hash", sa.LargeBinary(32)),
        sa.Column("context_type", sa.String(32)),
        sa.Column("context_snippet", sa.Text),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "source_url_hash",
            "cited_url_hash",
            name="uq_source_mentions_source_cited_hashes",
        ),
    )
    op.create_index(
        "ix_source_mentions_candidate_context",
        "source_mentions",
        ["candidate_id", "context_type"],
    )
    op.create_index(
        "ix_source_mentions_source_url_hash",
        "source_mentions",
        ["source_url_hash"],
    )
    op.create_index(
        "ix_source_mentions_cited_url_hash",
        "source_mentions",
        ["cited_url_hash"],
    )

    # --- rdap_snapshots ---
    op.create_table(
        "rdap_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Integer,
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("rdap_server", sa.Text),
        sa.Column("epp_statuses", postgresql.ARRAY(sa.String)),
        sa.Column("expiry_date", sa.Date),
        sa.Column("registrar", sa.Text),
        sa.Column("raw_response", postgresql.JSONB),
    )
    op.create_index(
        "ix_rdap_snapshots_candidate_observed",
        "rdap_snapshots",
        ["candidate_id", "observed_at"],
    )

    # --- availability_checks ---
    op.create_table(
        "availability_checks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Integer,
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32)),
        sa.Column("is_authoritative", sa.Boolean),
        sa.Column(
            "cost_micros",
            sa.BigInteger,
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("raw_response", postgresql.JSONB),
    )
    op.create_index(
        "ix_availability_checks_candidate_observed",
        "availability_checks",
        ["candidate_id", "observed_at"],
    )

    # --- http_observations ---
    op.create_table(
        "http_observations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Integer,
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("status_code", sa.Integer),
        sa.Column("final_url", sa.Text),
        sa.Column("is_parked", sa.Boolean),
        sa.Column("ns_signal", sa.String(64)),
    )

    # --- wayback_snapshots ---
    op.create_table(
        "wayback_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Integer,
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("first_capture", sa.Date),
        sa.Column("last_capture", sa.Date),
        sa.Column("capture_count", sa.Integer),
        sa.Column("cdx_summary", postgresql.JSONB),
    )

    # --- classification_runs ---
    op.create_table(
        "classification_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Integer,
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("model_used", sa.String(128), nullable=False),
        sa.Column("classifier_version", sa.String(64)),
        sa.Column("snapshot_ids", postgresql.ARRAY(sa.String)),
        sa.Column("classification", sa.String(32)),
        sa.Column("confidence", sa.Numeric),
        sa.Column(
            "cost_micros",
            sa.BigInteger,
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("raw_response", postgresql.JSONB),
    )
    op.create_index(
        "ix_classification_runs_cache_key",
        "classification_runs",
        ["cache_key"],
    )
    op.create_index(
        "ix_classification_runs_candidate_observed",
        "classification_runs",
        ["candidate_id", "observed_at"],
    )

    # --- registrar_quotes ---
    op.create_table(
        "registrar_quotes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Integer,
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("registrar", sa.String(64)),
        sa.Column("is_premium", sa.Boolean),
        sa.Column("quote_price_micros", sa.BigInteger),
        sa.Column("renewal_price_micros", sa.BigInteger),
        sa.Column(
            "quote_currency",
            sa.String(3),
            server_default=sa.text("'USD'"),
            nullable=False,
        ),
        sa.Column(
            "api_cost_micros",
            sa.BigInteger,
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("raw_response", postgresql.JSONB),
    )
    op.create_index(
        "ix_registrar_quotes_candidate_observed",
        "registrar_quotes",
        ["candidate_id", "observed_at"],
    )

    # --- outcomes ---
    op.create_table(
        "outcomes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Integer,
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("decision", sa.String(32)),
        sa.Column("pass_reason", sa.String(64)),
        sa.Column("notes", sa.Text),
        sa.Column("acquisition_cost_usd", sa.Numeric),
        sa.Column("acquisition_channel", sa.String(64)),
    )

    # --- Seed source_terms ---
    op.bulk_insert(
        sa.table(
            "source_terms",
            sa.column("kind", sa.String),
            sa.column("license", sa.String),
            sa.column("redistribution_allowed", sa.Boolean),
            sa.column("attribution_required", sa.Boolean),
            sa.column("rate_limit_notes", sa.Text),
            sa.column("robots_policy", sa.Text),
            sa.column("terms_url", sa.Text),
            sa.column("last_verified_at", sa.Date),
            sa.column("notes", sa.Text),
        ),
        [
            {
                "kind": "github_readme",
                "license": "mixed (per-repo)",
                "redistribution_allowed": True,
                "attribution_required": True,
                "rate_limit_notes": "REST 5k/hr auth; 60/hr anon; GraphQL 5k/hr",
                "robots_policy": "robots.txt allows; GHArchive CC-BY-4.0; cloned content carries upstream license",
                "terms_url": "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service",
                "last_verified_at": None,
                "notes": "Use Contents API + ETags before clone. Backoff on 403/429.",
            },
            {
                "kind": "wayback_cdx",
                "license": "archive.org Terms of Use",
                "redistribution_allowed": False,
                "attribution_required": True,
                "rate_limit_notes": "No published RPS; observed ~5/s OK; respect Retry-After",
                "robots_policy": "IA permits research; no bulk snapshot scraping",
                "terms_url": "https://archive.org/about/terms.php",
                "last_verified_at": None,
                "notes": "CDX index for metadata only; snapshots fetched on demand for classification.",
            },
            {
                "kind": "crossref_ref",
                "license": "CC0-1.0 (metadata)",
                "redistribution_allowed": True,
                "attribution_required": False,
                "rate_limit_notes": "Polite Pool 50/s with mailto in UA; public pool ~1-5/s",
                "robots_policy": "No robots restriction; Public Data File is bulk source",
                "terms_url": "https://www.crossref.org/documentation/retrieve-metadata/rest-api/",
                "last_verified_at": None,
                "notes": "Always identify with mailto for Polite Pool.",
            },
            {
                "kind": "pmc_jats",
                "license": "NIH public-domain / variable per-article",
                "redistribution_allowed": True,
                "attribution_required": False,
                "rate_limit_notes": "OAI-PMH polite use; FTP at ftp.ncbi.nlm.nih.gov/pub/pmc/",
                "robots_policy": "PMC OA for research/text-mining; respect per-article commercial-use tags",
                "terms_url": "https://www.ncbi.nlm.nih.gov/pmc/about/copyright/",
                "last_verified_at": None,
                "notes": "Filter article-level license; PMC OA Commercial vs NonCommercial subsets differ.",
            },
            {
                "kind": "patent_npl",
                "license": "public-domain (USPTO/EPO/WIPO)",
                "redistribution_allowed": True,
                "attribution_required": False,
                "rate_limit_notes": "BigQuery: respect maximum_bytes_billed; no external scraping",
                "robots_policy": "patents-public-data is Google Cloud public dataset",
                "terms_url": "https://cloud.google.com/blog/topics/public-datasets/google-patents-public-datasets-connecting-public-paid-and-private-patent-data",
                "last_verified_at": None,
                "notes": "USPTO data is US-public-domain; Google enrichment columns carry BQ ToS restrictions.",
            },
            {
                "kind": "czds_drop",
                "license": "ICANN CZDS Terms — research only",
                "redistribution_allowed": False,
                "attribution_required": True,
                "rate_limit_notes": "Daily download per TLD; no real-time API",
                "robots_policy": "CZDS forbids redistribution; data internal-use only",
                "terms_url": "https://czds.icann.org/terms-and-conditions",
                "last_verified_at": None,
                "notes": "Never share raw zone data. Aggregates only externally if ever needed.",
            },
        ],
    )

    # --- Seed initial scoring weights v1 (from PRD §4.5) ---
    op.bulk_insert(
        sa.table(
            "scoring_weights",
            sa.column("version", sa.Integer),
            sa.column("weights_json", postgresql.JSONB),
            sa.column("notes", sa.Text),
        ),
        [
            {
                "version": 1,
                "weights_json": {
                    "max_source_authority": 0.25,
                    "source_diversity_bonus": 0.10,
                    "referring_domains_score": 0.20,
                    "open_pagerank_score": 0.15,
                    "wayback_clean_score": 0.10,
                    "age_score": 0.10,
                    "spam_penalty": -0.10,
                    "tm_risk_penalty": -0.10,
                    "reputation_penalty": -0.10,
                },
                "notes": "Initial weights from PRD §4.5. Tunable from dashboard.",
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("outcomes")
    op.drop_index("ix_registrar_quotes_candidate_observed", table_name="registrar_quotes")
    op.drop_table("registrar_quotes")
    op.drop_index("ix_classification_runs_candidate_observed", table_name="classification_runs")
    op.drop_index("ix_classification_runs_cache_key", table_name="classification_runs")
    op.drop_table("classification_runs")
    op.drop_table("wayback_snapshots")
    op.drop_table("http_observations")
    op.drop_index("ix_availability_checks_candidate_observed", table_name="availability_checks")
    op.drop_table("availability_checks")
    op.drop_index("ix_rdap_snapshots_candidate_observed", table_name="rdap_snapshots")
    op.drop_table("rdap_snapshots")
    op.drop_index("ix_source_mentions_cited_url_hash", table_name="source_mentions")
    op.drop_index("ix_source_mentions_source_url_hash", table_name="source_mentions")
    op.drop_index("ix_source_mentions_candidate_context", table_name="source_mentions")
    op.drop_table("source_mentions")
    op.drop_index("ix_candidates_current_status", table_name="candidates")
    op.drop_index("ix_candidates_composite_score_not_filtered", table_name="candidates")
    op.drop_table("candidates")
    op.drop_table("scoring_weights")
    op.drop_table("source_terms")
    op.drop_table("sources")
