import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Brief(Base):
    __tablename__ = "briefs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    date_basis: Mapped[str] = mapped_column(String(32), nullable=False)
    detail_level: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_config_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("llm_provider_configs.id", ondelete="RESTRICT"), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    prompt_name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    filters_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    supporting_source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    selected_source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    included_source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    excluded_source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exclusion_reasons_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    structured_result_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    regenerated_from_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("briefs.id", ondelete="RESTRICT"), nullable=True)
    system_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="USER", server_default="USER")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BriefSource(Base):
    __tablename__ = "brief_sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brief_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("briefs.id", ondelete="RESTRICT"), nullable=False)
    source_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False)
    selection_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    collection_record_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ingestion_records.id", ondelete="RESTRICT"), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    exclusion_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    collection_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    citation_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BriefCitation(Base):
    __tablename__ = "brief_citations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brief_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("briefs.id", ondelete="RESTRICT"), nullable=False)
    citation_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False)
    claim_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="RESTRICT"), nullable=True)
    content_chunk_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("content_chunks.id", ondelete="RESTRICT"), nullable=True)
    quote_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TopicSynthesis(Base):
    __tablename__ = "topic_syntheses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("topics.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_config_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("llm_provider_configs.id", ondelete="RESTRICT"), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    prompt_name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    filters_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    structured_result_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TopicSynthesisSource(Base):
    __tablename__ = "topic_synthesis_sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    synthesis_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("topic_syntheses.id", ondelete="RESTRICT"), nullable=False)
    source_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False)
    included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    exclusion_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TopicSynthesisCitation(Base):
    __tablename__ = "topic_synthesis_citations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    synthesis_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("topic_syntheses.id", ondelete="RESTRICT"), nullable=False)
    citation_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False)
    claim_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="RESTRICT"), nullable=True)
    content_chunk_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("content_chunks.id", ondelete="RESTRICT"), nullable=True)
    quote_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
