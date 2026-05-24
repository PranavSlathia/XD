"""Scoring v3 — authority-first weights + low_authority hard filter.

The first real ingest validated a methodology issue with v2:

  - GitHub README links are rendered with rel="nofollow ugc", so the entire
    A2 source produces zero dofollow backlinks. ``max_source_authority``
    (repo stars) measures popularity of the *citing* repo, not the target
    domain's backlink authority, and those links don't pass PageRank.
  - v2's availability_score (0.30) over-rewarded mere availability, so a
    domain that was available but had no real backlinks (OPR 1.08, nofollow
    only) topped the ranking — useless to the operator.

v3 makes Open PageRank dominant (0.45) because OPR inherently weights
dofollow links (PageRank doesn't flow through rel=nofollow), and demotes
max_source_authority/diversity to 0.05 each (nofollow noise). availability
becomes a smaller additive (0.15) because the digest already hard-gates on
availability_confidence. The low_authority hard filter (in code) then knocks
out available-but-low-authority domains before they reach the shortlist.

No schema change — just seeds the new weights row.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_scoring_v3"
down_revision: str | None = "0002_opr_and_scoring_v2"
branch_labels = None
depends_on = None

_WEIGHTS_V3 = {
    "availability_score": 0.15,
    "max_source_authority": 0.05,
    "source_diversity_bonus": 0.05,
    "referring_domains_score": 0.10,
    "open_pagerank_score": 0.45,
    "wayback_clean_score": 0.10,
    "age_score": 0.10,
    "spam_penalty": -0.10,
    "tm_risk_penalty": -0.10,
    "reputation_penalty": -0.10,
}


def upgrade() -> None:
    op.bulk_insert(
        sa.table(
            "scoring_weights",
            sa.column("version", sa.Integer),
            sa.column("weights_json", postgresql.JSONB),
            sa.column("notes", sa.Text),
        ),
        [
            {
                "version": 3,
                "weights_json": _WEIGHTS_V3,
                "notes": (
                    "Authority-first. OPR dominates (0.45) because it inherently "
                    "weights dofollow links; max_source_authority demoted to 0.05 "
                    "(GitHub READMEs are rel=nofollow). Paired with the low_authority "
                    "hard filter (DH_OPR_MIN_AUTHORITY, default 3.0) to keep "
                    "available-but-worthless domains off the shortlist."
                ),
            },
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM scoring_weights WHERE version = 3")
