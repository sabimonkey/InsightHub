"""m4 llm analysis

Revision ID: e4b8c1d90a27
Revises: c7d2f4a91b08
Create Date: 2026-09-25 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e4b8c1d90a27"
down_revision: Union[str, Sequence[str], None] = "c7d2f4a91b08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("source_items", sa.Column("privacy_level", sa.String(length=32), nullable=False, server_default="PRIVATE"))
    op.create_table(
        "llm_provider_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("provider_type", sa.String(length=64), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=256), nullable=False),
        sa.Column("is_local", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("api_key_env", sa.String(length=128), nullable=True),
        sa.Column("capabilities_json", postgresql.JSONB(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("uq_llm_provider_configs_type", "llm_provider_configs", ["provider_type"], unique=True)
    op.create_table(
        "analysis_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("source_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("extracted_document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_config_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider_type", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=256), nullable=False),
        sa.Column("prompt_name", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("analysis_strategy", sa.String(length=32), nullable=True),
        sa.Column("input_extraction_status", sa.String(length=32), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["extracted_document_id"], ["extracted_documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["provider_config_id"], ["llm_provider_configs.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_analysis_runs_source_item_id", "analysis_runs", ["source_item_id"])
    op.create_index("uq_analysis_runs_current", "analysis_runs", ["source_item_id"], unique=True, postgresql_where=sa.text("is_current"))
    op.create_table(
        "analysis_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("analysis_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("raw_structured_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("analysis_run_id"),
    )
    op.create_table(
        "claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("analysis_result_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_type", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("importance", sa.Integer(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["analysis_result_id"], ["analysis_results.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_claims_analysis_result_id", "claims", ["analysis_result_id"])
    op.create_table(
        "evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quote_text", sa.Text(), nullable=True),
        sa.Column("start_offset", sa.Integer(), nullable=True),
        sa.Column("end_offset", sa.Integer(), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("evidence_strength", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["content_chunk_id"], ["content_chunks.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_evidence_claim_id", "evidence", ["claim_id"])


def downgrade() -> None:
    op.drop_index("ix_evidence_claim_id", table_name="evidence")
    op.drop_table("evidence")
    op.drop_index("ix_claims_analysis_result_id", table_name="claims")
    op.drop_table("claims")
    op.drop_table("analysis_results")
    op.drop_index("uq_analysis_runs_current", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_source_item_id", table_name="analysis_runs")
    op.drop_table("analysis_runs")
    op.drop_index("uq_llm_provider_configs_type", table_name="llm_provider_configs")
    op.drop_table("llm_provider_configs")
    op.drop_column("source_items", "privacy_level")
