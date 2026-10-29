"""Clone USER extraction into AUTOMATION_TEST benchmark sources."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.extraction import ContentChunk, ExtractedDocument, ExtractionRun
from app.models.source_item import SourceItem
from app.services.extraction.service import ExtractionService
from app.services.ingestion.service import IngestionService
from app.services.system_scope import AUTOMATION_TEST_SCOPE


def bench_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"insighthub_system_scope": AUTOMATION_TEST_SCOPE})


def clone_display_name(case_id: str) -> str:
    return f"bench-r1-{case_id}"


def ensure_clone(session: Session, settings: Settings, user_source_id: uuid.UUID, case_id: str) -> uuid.UUID:
    marker = clone_display_name(case_id)
    existing = session.scalar(
        select(SourceItem).where(SourceItem.display_name == marker, SourceItem.system_scope == AUTOMATION_TEST_SCOPE)
    )
    if existing is not None:
        return existing.id
    user = session.get(SourceItem, user_source_id)
    if user is None:
        raise LookupError(f"USER_SOURCE_NOT_FOUND:{user_source_id}")
    extraction = session.scalar(
        select(ExtractionRun).where(ExtractionRun.source_item_id == user_source_id, ExtractionRun.is_current.is_(True))
    )
    if extraction is None or extraction.status not in {"SUCCEEDED", "PARTIAL"}:
        raise LookupError(f"USER_SOURCE_NOT_EXTRACTED:{user_source_id}")
    document = session.scalar(select(ExtractedDocument).where(ExtractedDocument.extraction_run_id == extraction.id))
    if document is None or not (document.plain_text or "").strip():
        raise LookupError(f"USER_SOURCE_EMPTY:{user_source_id}")
    auto = bench_settings(settings)
    created = IngestionService(session, auto.raw_storage_path(), max_upload_size_bytes=settings.max_upload_size_bytes).ingest_text(
        document.plain_text[: min(len(document.plain_text), 120_000)]
    )
    created.source_item.display_name = marker
    created.source_item.system_scope = AUTOMATION_TEST_SCOPE
    session.commit()
    ExtractionService(
        session,
        auto.raw_storage_path(),
        auto.extracted_storage_path(),
        inline=True,
        chunk_max_chars=settings.chunk_max_chars,
        chunk_overlap_chars=settings.chunk_overlap_chars,
        max_pdf_pages=settings.max_pdf_pages,
        web_timeout=int(settings.web_fetch_timeout_seconds),
        web_max_bytes=settings.web_fetch_max_bytes,
        web_max_redirects=settings.web_fetch_max_redirects,
    ).schedule(created.source_item.id, "MANUAL", force=True)
    return created.source_item.id


def chunk_text_map(session: Session, source_id: uuid.UUID) -> dict[str, str]:
    extraction = session.scalar(
        select(ExtractionRun).where(ExtractionRun.source_item_id == source_id, ExtractionRun.is_current.is_(True))
    )
    if extraction is None:
        return {}
    document = session.scalar(select(ExtractedDocument).where(ExtractedDocument.extraction_run_id == extraction.id))
    if document is None:
        return {}
    chunks = list(session.scalars(select(ContentChunk).where(ContentChunk.extracted_document_id == document.id)))
    return {str(chunk.id): chunk.content or "" for chunk in chunks}
