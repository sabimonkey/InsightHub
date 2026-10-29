import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import get_ingestion_service
from app.models.extraction import ExtractionRun, ExtractedDocument
from app.services.display_title import inbox_list_title
from app.services.ingestion.service import IngestionService
from app.services.extraction_status import extraction_status_for_source
from app.services.research_note import analysis_status_for_source, content_analysis_summary
from app.schemas.ingestion import InboxItem, InboxPage

router = APIRouter(prefix="/api", tags=["inbox"])


@router.get("/inbox", response_model=InboxPage)
def list_inbox(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    filter: str = Query(default="all"),
    service: IngestionService = Depends(get_ingestion_service),
) -> InboxPage:
    rows, total = service.list_inbox(page, page_size, filter)
    source_ids = [source.id for _record, source, _asset in rows if source is not None]
    statuses: dict = {}
    if source_ids:
        runs = service.session.scalars(
            select(ExtractionRun)
            .where(ExtractionRun.source_item_id.in_(source_ids))
            .order_by(ExtractionRun.created_at.desc())
        ).all()
        for run in runs:
            statuses.setdefault(run.source_item_id, run.status)
    docs: dict[uuid.UUID, ExtractedDocument] = {}
    if source_ids:
        for doc in service.session.scalars(
            select(ExtractedDocument).where(ExtractedDocument.source_item_id.in_(source_ids)).order_by(ExtractedDocument.created_at.desc())
        ):
            docs.setdefault(doc.source_item_id, doc)
    items: list[InboxItem] = []
    for record, source, asset in rows:
        title = None
        analysis_status = None
        analysis_status_code = None
        summary_snippet = None
        extraction_status_label = None
        extraction_status_code = None
        extraction_user_message = None
        has_usable_content = False
        if source is not None:
            analysis_status, analysis_status_code = analysis_status_for_source(service.session, source.id)
            ext = extraction_status_for_source(service.session, source.id)
            extraction_status_label = ext["extraction_status"]
            extraction_status_code = ext["extraction_status_code"]
            extraction_user_message = ext["extraction_user_message"]
            has_usable_content = ext["has_usable_content"]
            doc = docs.get(source.id)
            summary = content_analysis_summary(service.session, source.id)
            title = inbox_list_title(source, document_title=doc.title if doc else None, analysis_summary=summary)
            summary_snippet = (summary[:240] + "…") if summary and len(summary) > 240 else summary
        items.append(
            InboxItem(
                ingestion_id=record.id,
                source_id=source.id if source else None,
                display_name=source.display_name if source else record.original_input,
                source_type=source.source_type if source else None,
                collected_at=record.collected_at,
                status=record.status,
                duplicate_detected=record.duplicate_detected,
                duplicate_reason=record.duplicate_reason,
                size_bytes=asset.size_bytes if asset else None,
                original_url=source.original_url if source else None,
                canonical_url=source.canonical_url if source else None,
                original_filename=asset.original_filename if asset else None,
                extraction_status=statuses.get(source.id) if source else None,
                extraction_status_label=extraction_status_label,
                extraction_status_code=extraction_status_code,
                extraction_user_message=extraction_user_message,
                has_usable_content=has_usable_content,
                title=title,
                analysis_status=analysis_status,
                analysis_status_code=analysis_status_code,
                summary_snippet=summary_snippet,
            )
        )
    return InboxPage(items=items, page=page, page_size=page_size, total=total)
