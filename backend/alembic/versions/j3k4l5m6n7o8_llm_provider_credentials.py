"""llm provider encrypted credentials

Revision ID: j3k4l5m6n7o8
Revises: i2j3k4l5m6n7
Create Date: 2026-10-19
"""

from alembic import op
import sqlalchemy as sa

revision = "j3k4l5m6n7o8"
down_revision = "i2j3k4l5m6n7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_provider_credentials",
        sa.Column("provider_type", sa.String(length=64), primary_key=True),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("llm_provider_credentials")
