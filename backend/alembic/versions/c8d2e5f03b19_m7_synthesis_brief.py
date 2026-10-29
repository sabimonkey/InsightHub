"""m7 synthesis and briefs

Revision ID: c8d2e5f03b19
Revises: b7c1d4e92a08
Create Date: 2026-09-25 16:40:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c8d2e5f03b19"
down_revision: Union[str, Sequence[str], None] = "b7c1d4e92a08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_uuid = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "briefs",
        sa.Column("id", _uuid, primary_key=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("date_basis", sa.String(32), nullable=False),
        sa.Column("detail_level", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("provider_type", sa.String(64), nullable=True),
        sa.Column("provider_config_id", _uuid, nullable=True),
        sa.Column("model_name", sa.String(256), nullable=True),
        sa.Column("prompt_name", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("filters_json", postgresql.JSONB(), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("supporting_source_count", sa.Integer(), nullable=False),
        sa.Column("selected_source_count", sa.Integer(), nullable=False),
        sa.Column("included_source_count", sa.Integer(), nullable=False),
        sa.Column("excluded_source_count", sa.Integer(), nullable=False),
        sa.Column("exclusion_reasons_json", postgresql.JSONB(), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=True),
        sa.Column("structured_result_json", postgresql.JSONB(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("regenerated_from_id", _uuid, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["provider_config_id"], ["llm_provider_configs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["regenerated_from_id"], ["briefs.id"], ondelete="RESTRICT"),
    )
    op.create_table(
        "brief_sources",
        sa.Column("id", _uuid, primary_key=True),
        sa.Column("brief_id", _uuid, nullable=False),
        sa.Column("source_item_id", _uuid, nullable=False),
        sa.Column("selection_reason", sa.String(64), nullable=False),
        sa.Column("collection_record_id", _uuid, nullable=True),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("exclusion_reason", sa.String(64), nullable=True),
        sa.Column("collection_count", sa.Integer(), nullable=False),
        sa.Column("citation_number", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["brief_id"], ["briefs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["collection_record_id"], ["ingestion_records.id"], ondelete="RESTRICT"),
    )
    op.create_table(
        "brief_citations",
        sa.Column("id", _uuid, primary_key=True),
        sa.Column("brief_id", _uuid, nullable=False),
        sa.Column("citation_number", sa.Integer(), nullable=False),
        sa.Column("source_item_id", _uuid, nullable=False),
        sa.Column("claim_id", _uuid, nullable=True),
        sa.Column("content_chunk_id", _uuid, nullable=True),
        sa.Column("quote_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["brief_id"], ["briefs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["content_chunk_id"], ["content_chunks.id"], ondelete="RESTRICT"),
    )
    op.create_table(
        "topic_syntheses",
        sa.Column("id", _uuid, primary_key=True),
        sa.Column("topic_id", _uuid, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("provider_type", sa.String(64), nullable=True),
        sa.Column("provider_config_id", _uuid, nullable=True),
        sa.Column("model_name", sa.String(256), nullable=True),
        sa.Column("prompt_name", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("filters_json", postgresql.JSONB(), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=True),
        sa.Column("structured_result_json", postgresql.JSONB(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["provider_config_id"], ["llm_provider_configs.id"], ondelete="RESTRICT"),
    )
    op.create_table(
        "topic_synthesis_sources",
        sa.Column("id", _uuid, primary_key=True),
        sa.Column("synthesis_id", _uuid, nullable=False),
        sa.Column("source_item_id", _uuid, nullable=False),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("exclusion_reason", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["synthesis_id"], ["topic_syntheses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="RESTRICT"),
    )
    op.create_table(
        "topic_synthesis_citations",
        sa.Column("id", _uuid, primary_key=True),
        sa.Column("synthesis_id", _uuid, nullable=False),
        sa.Column("citation_number", sa.Integer(), nullable=False),
        sa.Column("source_item_id", _uuid, nullable=False),
        sa.Column("claim_id", _uuid, nullable=True),
        sa.Column("content_chunk_id", _uuid, nullable=True),
        sa.Column("quote_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["synthesis_id"], ["topic_syntheses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["content_chunk_id"], ["content_chunks.id"], ondelete="RESTRICT"),
    )


def downgrade() -> None:
    op.drop_table("topic_synthesis_citations")
    op.drop_table("topic_synthesis_sources")
    op.drop_table("topic_syntheses")
    op.drop_table("brief_citations")
    op.drop_table("brief_sources")
    op.drop_table("briefs")
