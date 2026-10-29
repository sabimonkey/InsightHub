"""m2 content extraction

Revision ID: b2e4d7a81c30
Revises: a1f3c8d92b47
Create Date: 2026-09-25 11:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2e4d7a81c30"
down_revision: Union[str, Sequence[str], None] = "a1f3c8d92b47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "extraction_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("source_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("extractor_type", sa.String(length=64), nullable=True),
        sa.Column("extractor_version", sa.String(length=64), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_asset_id"], ["source_assets.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_extraction_runs_source_item_id", "extraction_runs", ["source_item_id"])
    op.create_index(
        "uq_extraction_runs_current",
        "extraction_runs",
        ["source_item_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_table(
        "extracted_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("extraction_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("extractor_type", sa.String(length=64), nullable=False),
        sa.Column("extractor_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("plain_text", sa.Text(), nullable=False),
        sa.Column("structured_text", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["extraction_run_id"], ["extraction_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_asset_id"], ["source_assets.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("extraction_run_id", name="uq_extracted_documents_run"),
    )
    op.create_table(
        "content_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("extracted_document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("heading_path", postgresql.JSONB(), nullable=True),
        sa.Column("chunk_type", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["extracted_document_id"], ["extracted_documents.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_content_chunks_document_sequence", "content_chunks", ["extracted_document_id", "sequence"])


def downgrade() -> None:
    op.drop_index("ix_content_chunks_document_sequence", table_name="content_chunks")
    op.drop_table("content_chunks")
    op.drop_table("extracted_documents")
    op.drop_index("uq_extraction_runs_current", table_name="extraction_runs")
    op.drop_index("ix_extraction_runs_source_item_id", table_name="extraction_runs")
    op.drop_table("extraction_runs")
