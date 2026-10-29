"""Soft delete and restore for knowledge library sources."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ingestion_record import IngestionRecord
from app.models.organization import Category, SourceCategoryAssignment
from app.models.source_item import SourceItem

TRASH_RETENTION_DAYS = 7


class SourceLifecycleError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def source_is_visible(source: SourceItem | None) -> bool:
    return source is not None and source.deleted_at is None


def trash_cutoff(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now - timedelta(days=TRASH_RETENTION_DAYS)


def soft_delete_source(session: Session, source_id: uuid.UUID) -> SourceItem:
    source = session.get(SourceItem, source_id)
    if source is None:
        raise SourceLifecycleError("SOURCE_NOT_FOUND", "找不到资料。")
    if source.deleted_at is not None:
        return source
    source.deleted_at = datetime.now(timezone.utc)
    session.commit()
    return source


def restore_source(session: Session, source_id: uuid.UUID) -> SourceItem:
    source = session.get(SourceItem, source_id)
    if source is None:
        raise SourceLifecycleError("SOURCE_NOT_FOUND", "找不到资料。")
    if source.deleted_at is None:
        return source
    cutoff = trash_cutoff()
    if source.deleted_at < cutoff:
        raise SourceLifecycleError("TRASH_EXPIRED", "该资料已超过 7 天恢复期限。")
    source.deleted_at = None
    session.commit()
    return source


def list_trash_sources(session: Session, *, scope_filter) -> list[dict]:
    cutoff = trash_cutoff()
    rows = list(
        session.scalars(
            select(SourceItem)
            .where(scope_filter)
            .where(SourceItem.deleted_at.is_not(None))
            .where(SourceItem.deleted_at >= cutoff)
            .order_by(SourceItem.deleted_at.desc())
        )
    )
    items = []
    now = datetime.now(timezone.utc)
    for source in rows:
        deleted = source.deleted_at
        assert deleted is not None
        days_left = max(0, TRASH_RETENTION_DAYS - (now - deleted).days)
        slugs: list[str] = []
        for row in session.scalars(
            select(SourceCategoryAssignment).where(
                SourceCategoryAssignment.source_item_id == source.id,
                SourceCategoryAssignment.status == "ACTIVE",
            )
        ):
            category = session.get(Category, row.category_id)
            if category:
                slugs.append(category.slug)
        collected = list(
            session.scalars(
                select(IngestionRecord.collected_at).where(
                    IngestionRecord.source_item_id == source.id,
                    IngestionRecord.origin == "USER_COLLECTION",
                    IngestionRecord.status == "STORED",
                )
            )
        )
        first = min(collected) if collected else None
        items.append(
            {
                "source_id": source.id,
                "title": source.display_name or "Untitled Source",
                "categories": slugs,
                "first_collected_at": first,
                "deleted_at": deleted,
                "days_until_purge_ui": days_left,
            }
        )
    return items
