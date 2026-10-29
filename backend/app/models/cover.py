import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CoverGenerationRun(Base):
    __tablename__ = "cover_generation_runs"
    __table_args__ = (Index("ix_cover_generation_runs_source", "source_item_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False)
    deployment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("llm_model_deployments.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="QUEUED")
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False, default="cover-v1")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    candidate_review_state: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SourceCoverAsset(Base):
    __tablename__ = "source_cover_assets"
    __table_args__ = (
        Index("ix_source_cover_assets_source", "source_item_id"),
        Index("uq_source_cover_assets_current", "source_item_id", unique=True, postgresql_where=text("is_current IS TRUE")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    generation_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("cover_generation_runs.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CoverPromptRevision(Base):
    __tablename__ = "cover_prompt_revisions"
    __table_args__ = (
        Index(
            "uq_cover_prompt_revisions_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active IS TRUE"),
            sqlite_where=text("is_active = 1"),
        ),
    )

    revision: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
