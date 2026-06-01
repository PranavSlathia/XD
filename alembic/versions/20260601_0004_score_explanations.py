"""Add score explanations to candidates.

Revision ID: 0004_score_explanations
Revises: 0003_scoring_v3
Create Date: 2026-06-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_score_explanations"
down_revision: str | None = "0003_scoring_v3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("candidates", sa.Column("score_breakdown", postgresql.JSONB(), nullable=True))
    op.add_column("candidates", sa.Column("top_reasons", postgresql.ARRAY(sa.String()), nullable=True))
    op.execute("UPDATE candidates SET score_version = NULL")


def downgrade() -> None:
    op.drop_column("candidates", "top_reasons")
    op.drop_column("candidates", "score_breakdown")
