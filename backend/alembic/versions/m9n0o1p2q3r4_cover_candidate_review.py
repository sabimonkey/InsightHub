"""Persist user review choice for generated cover candidates."""

from alembic import op
import sqlalchemy as sa


revision = "m9n0o1p2q3r4"
down_revision = "l6m7n8o9p0q1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cover_generation_runs",
        sa.Column("candidate_review_state", sa.String(length=24), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cover_generation_runs", "candidate_review_state")
