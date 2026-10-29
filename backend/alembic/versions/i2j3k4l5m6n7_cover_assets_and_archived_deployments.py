"""cover assets and archived llm deployments

Revision ID: i2j3k4l5m6n7
Revises: h1a2b3c4d5e6
Create Date: 2026-10-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "i2j3k4l5m6n7"
down_revision = "h1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_model_deployments", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_llm_model_deployments_archived_at", "llm_model_deployments", ["archived_at"])

    op.create_table(
        "cover_generation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("deployment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("llm_model_deployments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False, server_default="QUEUED"),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False, server_default="cover-v1"),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_cover_generation_runs_source", "cover_generation_runs", ["source_item_id"])

    op.create_table(
        "source_cover_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("provider_type", sa.String(64), nullable=True),
        sa.Column("model_id", sa.String(512), nullable=True),
        sa.Column("prompt_hash", sa.String(64), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("generation_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cover_generation_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_source_cover_assets_source", "source_cover_assets", ["source_item_id"])
    op.create_index(
        "uq_source_cover_assets_current",
        "source_cover_assets",
        ["source_item_id"],
        unique=True,
        postgresql_where=sa.text("is_current IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index("uq_source_cover_assets_current", table_name="source_cover_assets")
    op.drop_index("ix_source_cover_assets_source", table_name="source_cover_assets")
    op.drop_table("source_cover_assets")
    op.drop_index("ix_cover_generation_runs_source", table_name="cover_generation_runs")
    op.drop_table("cover_generation_runs")
    op.drop_index("ix_llm_model_deployments_archived_at", table_name="llm_model_deployments")
    op.drop_column("llm_model_deployments", "archived_at")
