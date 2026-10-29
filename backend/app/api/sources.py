import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.api.deps import get_extraction_service, get_ingestion_service
from app.api.extraction import _view
from app.api.presenters import asset_summary, ingestion_summary, source_summary
from app.core.config import get_settings
from app.schemas.ingestion import SourceDetail
from app.services.extraction.service import ExtractionService
from app.services.ingestion.service import IngestionService
from app.services.research_note import build_research_note, research_note_markdown
from app.services.synthesis.exporting import write_docx, write_markdown, write_pdf

router = APIRouter(prefix="/api", tags=["sources"])


@router.get("/sources/{source_id}", response_model=SourceDetail)
def get_source(
    source_id: uuid.UUID,
    service: IngestionService = Depends(get_ingestion_service),
    extraction: ExtractionService = Depends(get_extraction_service),
) -> SourceDetail:
    source, asset, records = service.get_source(source_id)
    run, document, chunks = extraction.current_view(source_id)
    return SourceDetail(
        source=source_summary(source),
        asset=asset_summary(asset),
        ingestions=[ingestion_summary(record) for record in records],
        extraction=_view(run, document, chunks),
    )


@router.get("/sources/{source_id}/note")
def get_research_note(source_id: uuid.UUID, service: IngestionService = Depends(get_ingestion_service)) -> dict:
    settings = get_settings()
    try:
        return build_research_note(service.session, source_id, settings)
    except LookupError:
        raise HTTPException(status_code=404, detail="找不到该资料。") from None


@router.get("/sources/{source_id}/note/export")
def export_research_note(source_id: uuid.UUID, format: str = "markdown", service: IngestionService = Depends(get_ingestion_service)) -> Response:
    from datetime import date
    from urllib.parse import quote

    from app.services.synthesis.exporting import safe_filename

    settings = get_settings()
    try:
        note = build_research_note(service.session, source_id, settings)
    except LookupError:
        raise HTTPException(status_code=404, detail="找不到该资料。") from None
    markdown = research_note_markdown(note)
    title = note.get("title") or "research-note"
    export_doc = type("ExportDoc", (), {"title": title, "content_markdown": markdown, "filters_json": {}, "start_date": date.today(), "end_date": date.today()})()
    name = safe_filename(title)
    if format == "markdown":
        payload = write_markdown(export_doc)
        media = "text/markdown; charset=utf-8"
        filename = f"{name}.md"
    elif format == "docx":
        payload = write_docx(export_doc, [])
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        filename = f"{name}.docx"
    elif format == "pdf":
        payload = write_pdf(export_doc)
        media = "application/pdf"
        filename = f"{name}.pdf"
    else:
        raise HTTPException(status_code=400, detail="不支持的导出格式。")
    return Response(content=payload, media_type=media, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})
