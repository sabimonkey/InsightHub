"""m1 universal inbox

Revision ID: a1f3c8d92b47
Revises: 2e388c0d4224
Create Date: 2026-09-25 11:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1f3c8d92b47"
down_revision: Union[str, Sequence[str], None] = "2e388c0d4224"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("original_url", sa.Text(), nullable=True),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "uq_source_items_canonical_url",
        "source_items",
        ["canonical_url"],
        unique=True,
        postgresql_where=sa.text("canonical_url IS NOT NULL"),
    )
    op.create_index(
        "uq_source_items_text_hash",
        "source_items",
        ["content_hash"],
        unique=True,
        postgresql_where=sa.text("source_type = 'TEXT' AND content_hash IS NOT NULL"),
    )
    op.create_table(
        "source_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("source_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("stored_path", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("source_item_id", name="uq_source_assets_source_item_id"),
        sa.UniqueConstraint("sha256", name="uq_source_assets_sha256"),
    )
    op.create_table(
        "ingestion_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("source_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ingestion_type", sa.String(length=32), nullable=False),
        sa.Column("original_input", sa.Text(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duplicate_detected", sa.Boolean(), nullable=False),
        sa.Column("duplicate_reason", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_ingestion_records_collected_at", "ingestion_records", ["collected_at"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_records_collected_at", table_name="ingestion_records")
    op.drop_table("ingestion_records")
    op.drop_table("source_assets")
    op.drop_index("uq_source_items_text_hash", table_name="source_items")
    op.drop_index("uq_source_items_canonical_url", table_name="source_items")
    op.drop_table("source_items")
