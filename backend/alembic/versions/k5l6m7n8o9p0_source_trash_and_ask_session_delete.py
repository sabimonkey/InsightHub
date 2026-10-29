"""source soft delete and ask session soft delete

Revision ID: k5l6m7n8o9p0
Revises: j3k4l5m6n7o8
Create Date: 2026-10-20
"""

from alembic import op
import sqlalchemy as sa

revision = "k5l6m7n8o9p0"
down_revision = "j3k4l5m6n7o8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("source_items", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_source_items_deleted_at", "source_items", ["deleted_at"], unique=False)
    op.add_column("ask_sessions", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "ask_sessions",
        sa.Column("title_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_ask_sessions_deleted_at", "ask_sessions", ["deleted_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ask_sessions_deleted_at", table_name="ask_sessions")
    op.drop_column("ask_sessions", "title_locked")
    op.drop_column("ask_sessions", "deleted_at")
    op.drop_index("ix_source_items_deleted_at", table_name="source_items")
    op.drop_column("source_items", "deleted_at")
