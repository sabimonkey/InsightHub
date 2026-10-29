"""m6 retrieval and ask

Revision ID: a6d1e3f72c45
Revises: f5c9d2e81b36
Create Date: 2026-09-25 16:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "a6d1e3f72c45"
down_revision: Union[str, Sequence[str], None] = "f5c9d2e81b36"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.add_column(
        "content_chunks",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', coalesce(content, ''))", persisted=True),
            nullable=True,
        ),
    )
    op.create_index("ix_content_chunks_search", "content_chunks", ["search_vector"], postgresql_using="gin")
    op.create_index("ix_content_chunks_trgm", "content_chunks", ["content"], postgresql_using="gin", postgresql_ops={"content": "gin_trgm_ops"})
    op.create_table(
        "embedding_provider_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("provider_type", sa.String(64), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("model", sa.String(256), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("is_local", sa.Boolean(), nullable=False),
        sa.Column("api_key_env", sa.String(128), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("uq_embedding_provider_type", "embedding_provider_configs", ["provider_type"], unique=True)
    op.create_table(
        "embedding_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_config_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model", sa.String(256), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["provider_config_id"], ["embedding_provider_configs.id"], ondelete="RESTRICT"),
    )
    op.create_index("uq_embedding_profiles_active", "embedding_profiles", ["is_active"], unique=True, postgresql_where=sa.text("is_active"))
    op.create_table(
        "chunk_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("content_chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_type", sa.String(64), nullable=False),
        sa.Column("model_name", sa.String(256), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(32), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["content_chunk_id"], ["content_chunks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["embedding_profile_id"], ["embedding_profiles.id"], ondelete="RESTRICT"),
    )
    op.create_index("uq_chunk_embedding_profile", "chunk_embeddings", ["content_chunk_id", "embedding_profile_id"], unique=True)
    op.execute("CREATE INDEX ix_chunk_embeddings_hnsw ON chunk_embeddings USING hnsw (embedding vector_cosine_ops)")
    op.create_table(
        "indexing_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("embedding_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("total_chunks", sa.Integer(), nullable=False),
        sa.Column("processed_chunks", sa.Integer(), nullable=False),
        sa.Column("failed_chunks", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["embedding_profile_id"], ["embedding_profiles.id"], ondelete="RESTRICT"),
    )
    op.create_table(
        "ask_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "ask_turns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("provider_type", sa.String(64), nullable=True),
        sa.Column("model_name", sa.String(256), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("answer_markdown", sa.Text(), nullable=True),
        sa.Column("retrieval_query", sa.Text(), nullable=False),
        sa.Column("filters_json", postgresql.JSONB(), nullable=False),
        sa.Column("excluded_sensitive_source_count", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["ask_sessions.id"], ondelete="RESTRICT"),
    )
    op.create_table(
        "ask_citations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ask_turn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("citation_number", sa.Integer(), nullable=False),
        sa.Column("quote_text", sa.Text(), nullable=True),
        sa.Column("retrieval_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["ask_turn_id"], ["ask_turns.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["content_chunk_id"], ["content_chunks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="RESTRICT"),
    )


def downgrade() -> None:
    op.drop_table("ask_citations")
    op.drop_table("ask_turns")
    op.drop_table("ask_sessions")
    op.drop_table("indexing_runs")
    op.execute("DROP INDEX IF EXISTS ix_chunk_embeddings_hnsw")
    op.drop_index("uq_chunk_embedding_profile", table_name="chunk_embeddings")
    op.drop_table("chunk_embeddings")
    op.drop_index("uq_embedding_profiles_active", table_name="embedding_profiles")
    op.drop_table("embedding_profiles")
    op.drop_index("uq_embedding_provider_type", table_name="embedding_provider_configs")
    op.drop_table("embedding_provider_configs")
    op.drop_index("ix_content_chunks_trgm", table_name="content_chunks")
    op.drop_index("ix_content_chunks_search", table_name="content_chunks")
    op.drop_column("content_chunks", "search_vector")
