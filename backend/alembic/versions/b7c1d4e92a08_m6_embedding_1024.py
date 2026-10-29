"""replace 32-d embeddings with production vector(1024)

Revision ID: b7c1d4e92a08
Revises: a6d1e3f72c45
Create Date: 2026-09-25 16:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "b7c1d4e92a08"
down_revision: Union[str, Sequence[str], None] = "a6d1e3f72c45"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM chunk_embeddings")
    op.execute("DELETE FROM indexing_runs")
    op.execute("UPDATE embedding_profiles SET is_active = false WHERE dimensions <> 1024")
    op.execute("DROP INDEX IF EXISTS ix_chunk_embeddings_hnsw")
    op.drop_column("chunk_embeddings", "embedding")
    op.add_column("chunk_embeddings", sa.Column("embedding", Vector(1024), nullable=False))
    op.execute("CREATE INDEX ix_chunk_embeddings_hnsw ON chunk_embeddings USING hnsw (embedding vector_cosine_ops)")


def downgrade() -> None:
    op.execute("DELETE FROM chunk_embeddings")
    op.execute("DELETE FROM indexing_runs")
    op.execute("UPDATE embedding_profiles SET is_active = false")
    op.execute("DROP INDEX IF EXISTS ix_chunk_embeddings_hnsw")
    op.drop_column("chunk_embeddings", "embedding")
    op.add_column("chunk_embeddings", sa.Column("embedding", Vector(32), nullable=False))
    op.execute("CREATE INDEX ix_chunk_embeddings_hnsw ON chunk_embeddings USING hnsw (embedding vector_cosine_ops)")
