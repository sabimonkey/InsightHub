"""Auto-enqueue analysis after successful extraction (M-PIPELINE-R2)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.analysis import AnalysisRun
from app.models.extraction import ExtractedDocument, ExtractionRun
from app.models.source_item import SourceItem
from app.services.system_scope import USER_SCOPE

_ACTIVE = {"PENDING", "QUEUED", "RUNNING"}
_TERMINAL_OK = {"SUCCEEDED", "PARTIAL"}


def _current_document(session: Session, source_id: uuid.UUID) -> ExtractedDocument | None:
    extraction = session.scalar(
        select(ExtractionRun).where(ExtractionRun.source_item_id == source_id, ExtractionRun.is_current.is_(True))
    )
    if extraction is None or extraction.status not in _TERMINAL_OK:
        return None
    return session.scalar(select(ExtractedDocument).where(ExtractedDocument.extraction_run_id == extraction.id))


def should_skip_auto_analysis(session: Session, source_id: uuid.UUID, document: ExtractedDocument) -> str | None:
    active = session.scalar(
        select(AnalysisRun)
        .where(AnalysisRun.source_item_id == source_id, AnalysisRun.status.in_(_ACTIVE))
        .order_by(AnalysisRun.created_at.desc())
    )
    if active is not None:
        return "ACTIVE_RUN"
    done = session.scalar(
        select(AnalysisRun)
        .where(
            AnalysisRun.source_item_id == source_id,
            AnalysisRun.extracted_document_id == document.id,
            AnalysisRun.status.in_(_TERMINAL_OK),
        )
        .order_by(AnalysisRun.created_at.desc())
    )
    if done is not None:
        return "ALREADY_ANALYZED"
    return None


def schedule_analysis_after_extraction(
    session: Session,
    source_id: uuid.UUID,
    *,
    settings: Settings | None = None,
    inline: bool = False,
) -> AnalysisRun | None:
    settings = settings or get_settings()
    if not getattr(settings, "pipeline_auto_analysis_enabled", True):
        return None
    source = session.get(SourceItem, source_id)
    if source is None or source.deleted_at is not None or source.system_scope != USER_SCOPE:
        return None
    document = _current_document(session, source_id)
    if document is None:
        return None
    skip = should_skip_auto_analysis(session, source_id, document)
    if skip:
        return None
    active = session.scalar(
        select(AnalysisRun)
        .where(AnalysisRun.source_item_id == source_id, AnalysisRun.status.in_(_ACTIVE))
        .order_by(AnalysisRun.created_at.desc())
    )
    if active is not None:
        return active
    from app.jobs.analysis import enqueue_analysis
    from app.services.analysis.service import AnalysisService

    service = AnalysisService(session, inline=inline, settings=settings, enqueue=enqueue_analysis)
    try:
        return service.start(source_id)
    except Exception:
        return None
