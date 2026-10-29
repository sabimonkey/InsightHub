import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SourceDiscoveryRun(Base):
    __tablename__ = "source_discovery_runs"
    __table_args__ = (Index("ix_source_discovery_runs_source_item_id", "source_item_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    resolver_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resolver_version: Mapped[str] = mapped_column(String(64), nullable=False)
    query_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OriginalSourceCandidate(Base):
    __tablename__ = "original_source_candidates"
    __table_args__ = (
        Index("ix_original_source_candidates_run_id", "discovery_run_id"),
        Index("ix_original_source_candidates_source_item_id", "source_item_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    discovery_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_discovery_runs.id", ondelete="RESTRICT"), nullable=False
    )
    source_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False
    )
    candidate_url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_candidate_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    candidate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    match_reasons_json: Mapped[list] = mapped_column(JSONB, nullable=False)
    evidence_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SourceRelation(Base):
    __tablename__ = "source_relations"
    __table_args__ = (
        UniqueConstraint("from_source_id", "to_source_id", "relation_type", name="uq_source_relations_edge"),
        Index("ix_source_relations_from_source_id", "from_source_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False
    )
    to_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    confirmed_by: Mapped[str] = mapped_column(String(32), nullable=False)
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("original_source_candidates.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
