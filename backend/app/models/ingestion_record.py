import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class IngestionRecord(Base):
    __tablename__ = "ingestion_records"
    __table_args__ = (Index("ix_ingestion_records_collected_at", "collected_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_items.id", ondelete="RESTRICT"),
        nullable=True,
    )
    ingestion_type: Mapped[str] = mapped_column(String(32), nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False, default="USER_COLLECTION", server_default="USER_COLLECTION")
    original_input: Mapped[str] = mapped_column(Text, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duplicate_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duplicate_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    source_item: Mapped["SourceItem | None"] = relationship(back_populates="ingestions")
