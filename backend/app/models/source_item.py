import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SourceItem(Base):
    __tablename__ = "source_items"
    __table_args__ = (
        Index(
            "uq_source_items_canonical_url",
            "canonical_url",
            unique=True,
            postgresql_where=text("canonical_url IS NOT NULL"),
        ),
        Index(
            "uq_source_items_text_hash",
            "content_hash",
            unique=True,
            postgresql_where=text("source_type = 'TEXT' AND content_hash IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    original_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    system_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="USER", server_default="USER")
    privacy_level: Mapped[str] = mapped_column(String(32), nullable=False, default="PRIVATE", server_default="PRIVATE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    assets: Mapped[list["SourceAsset"]] = relationship(back_populates="source_item")
    ingestions: Mapped[list["IngestionRecord"]] = relationship(back_populates="source_item")
