import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.services.retrieval.constants import EMBEDDING_DIMENSIONS


class EmbeddingProviderConfig(Base):
    __tablename__ = "embedding_provider_configs"
    __table_args__ = (Index("uq_embedding_provider_type", "provider_type", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    model: Mapped[str] = mapped_column(String(256), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    is_local: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    api_key_env: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EmbeddingProfile(Base):
    __tablename__ = "embedding_profiles"
    __table_args__ = (Index("uq_embedding_profiles_active", "is_active", unique=True, postgresql_where=text("is_active")),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_config_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("embedding_provider_configs.id", ondelete="RESTRICT"), nullable=False)
    model: Mapped[str] = mapped_column(String(256), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (Index("uq_chunk_embedding_profile", "content_chunk_id", "embedding_profile_id", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content_chunk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("content_chunks.id", ondelete="RESTRICT"), nullable=False)
    embedding_profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("embedding_profiles.id", ondelete="RESTRICT"), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(256), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class IndexingRun(Base):
    __tablename__ = "indexing_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=True)
    embedding_profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("embedding_profiles.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AskSession(Base):
    __tablename__ = "ask_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="USER", server_default="USER")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    title_locked: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")


class AskTurn(Base):
    __tablename__ = "ask_turns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ask_sessions.id", ondelete="RESTRICT"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    provider_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    answer_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieval_query: Mapped[str] = mapped_column(Text, nullable=False)
    filters_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    excluded_sensitive_source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AskCitation(Base):
    __tablename__ = "ask_citations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ask_turn_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ask_turns.id", ondelete="RESTRICT"), nullable=False)
    content_chunk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("content_chunks.id", ondelete="RESTRICT"), nullable=False)
    source_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False)
    citation_number: Mapped[int] = mapped_column(Integer, nullable=False)
    quote_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieval_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
