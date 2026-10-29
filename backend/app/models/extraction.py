import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"
    __table_args__ = (
        Index("ix_extraction_runs_source_item_id", "source_item_id"),
        Index(
            "uq_extraction_runs_current",
            "source_item_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False
    )
    source_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_assets.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    extractor_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extractor_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    document: Mapped["ExtractedDocument | None"] = relationship(back_populates="run")


class ExtractedDocument(Base):
    __tablename__ = "extracted_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    extraction_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("extraction_runs.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    source_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False
    )
    source_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_assets.id", ondelete="RESTRICT"), nullable=True
    )
    extractor_type: Mapped[str] = mapped_column(String(64), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    plain_text: Mapped[str] = mapped_column(Text, nullable=False)
    structured_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    run: Mapped[ExtractionRun] = relationship(back_populates="document")
    chunks: Mapped[list["ContentChunk"]] = relationship(back_populates="document")


class ContentChunk(Base):
    __tablename__ = "content_chunks"
    __table_args__ = (Index("ix_content_chunks_document_sequence", "extracted_document_id", "sequence"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    extracted_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extracted_documents.id", ondelete="RESTRICT"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    heading_path: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    chunk_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    document: Mapped[ExtractedDocument] = relationship(back_populates="chunks")
