"""m3 source discovery

Revision ID: c7d2f4a91b08
Revises: b2e4d7a81c30
Create Date: 2026-09-25 12:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7d2f4a91b08"
down_revision: Union[str, Sequence[str], None] = "b2e4d7a81c30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ingestion_records",
        sa.Column("origin", sa.String(length=32), nullable=False, server_default="USER_COLLECTION"),
    )
    op.create_table(
        "source_discovery_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("source_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("resolver_type", sa.String(length=64), nullable=False),
        sa.Column("resolver_version", sa.String(length=64), nullable=False),
        sa.Column("query_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_source_discovery_runs_source_item_id", "source_discovery_runs", ["source_item_id"])
    op.create_table(
        "original_source_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("discovery_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_url", sa.Text(), nullable=False),
        sa.Column("normalized_candidate_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("publisher", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("candidate_type", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("match_reasons_json", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_json", postgresql.JSONB(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["discovery_run_id"], ["source_discovery_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_original_source_candidates_run_id", "original_source_candidates", ["discovery_run_id"])
    op.create_index("ix_original_source_candidates_source_item_id", "original_source_candidates", ["source_item_id"])
    op.create_table(
        "source_relations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("from_source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False),
        sa.Column("confirmed_by", sa.String(length=32), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["from_source_id"], ["source_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["to_source_id"], ["source_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["candidate_id"], ["original_source_candidates.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("from_source_id", "to_source_id", "relation_type", name="uq_source_relations_edge"),
    )
    op.create_index("ix_source_relations_from_source_id", "source_relations", ["from_source_id"])


def downgrade() -> None:
    op.drop_index("ix_source_relations_from_source_id", table_name="source_relations")
    op.drop_table("source_relations")
    op.drop_index("ix_original_source_candidates_source_item_id", table_name="original_source_candidates")
    op.drop_index("ix_original_source_candidates_run_id", table_name="original_source_candidates")
    op.drop_table("original_source_candidates")
    op.drop_index("ix_source_discovery_runs_source_item_id", table_name="source_discovery_runs")
    op.drop_table("source_discovery_runs")
    op.drop_column("ingestion_records", "origin")
