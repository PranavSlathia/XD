"""Add OPR/referring-domains columns + deadness-aware scoring_weights v2.

Why:
  - v1 scoring left ``open_pagerank`` and ``referring_domains`` hardcoded to 0
    in the worker (no column to read from), so 35% of the weight budget was
    inert and the composite topped out ~29 — below the digest threshold,
    making the daily shortlist permanently empty.
  - v1 had no deadness signal, so live mega-domains (github.com, google.com)
    ranked above genuinely available domains.

This migration adds ``candidates.open_pagerank`` + ``candidates.referring_domains``
and seeds scoring_weights v2, which introduces ``availability_score`` (dominant
weight) and activates ``open_pagerank_score``. Bumping the version triggers the
scoring worker to recompute every candidate against v2.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_opr_and_scoring_v2"
down_revision: str | None = "0001_initial_schema"
branch_labels = None
depends_on = None

_WEIGHTS_V2 = {
    "availability_score": 0.30,
    "max_source_authority": 0.15,
    "source_diversity_bonus": 0.10,
    "referring_domains_score": 0.10,
    "open_pagerank_score": 0.20,
    "wayback_clean_score": 0.10,
    "age_score": 0.05,
    "spam_penalty": -0.10,
    "tm_risk_penalty": -0.10,
    "reputation_penalty": -0.10,
}


def upgrade() -> None:
    op.add_column("candidates", sa.Column("open_pagerank", sa.Numeric(), nullable=True))
    op.add_column("candidates", sa.Column("referring_domains", sa.Integer(), nullable=True))
    op.bulk_insert(
        sa.table(
            "scoring_weights",
            sa.column("version", sa.Integer),
            sa.column("weights_json", postgresql.JSONB),
            sa.column("notes", sa.Text),
        ),
        [
            {
                "version": 2,
                "weights_json": _WEIGHTS_V2,
                "notes": (
                    "Deadness-aware. Adds availability_score (0.30) so live/unchecked "
                    "domains can't top the ranking; activates open_pagerank_score (0.20, "
                    "now persisted). Positive weights sum to 1.0."
                ),
            },
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM scoring_weights WHERE version = 2")
    op.drop_column("candidates", "referring_domains")
    op.drop_column("candidates", "open_pagerank")
