import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.deps import get_extraction_service
from app.models.extraction import ContentChunk, ExtractedDocument, ExtractionRun
from app.schemas.ingestion import (
    ChunkSummary,
    ExtractionDocumentSummary,
    ExtractionRunSummary,
    ExtractionView,
)
from app.services.extraction.enums import ExtractionTrigger
from app.services.extraction.service import ExtractionService
from app.models.source_item import SourceItem
from app.services.system_scope import scope_visible_for_api

router = APIRouter(prefix="/api", tags=["extraction"])


class UserTextSupplementBody(BaseModel):
    text: str = Field(min_length=1, max_length=500_000)


def _view(run: ExtractionRun | None, document: ExtractedDocument | None, chunks: list[ContentChunk]) -> ExtractionView:
    return ExtractionView(
        run=None
        if run is None
        else ExtractionRunSummary(
            id=run.id,
            status=run.status,
            trigger=run.trigger,
            extractor_type=run.extractor_type,
            extractor_version=run.extractor_version,
            is_current=run.is_current,
            error_code=run.error_code,
            error_message=run.error_message,
            created_at=run.created_at,
            updated_at=run.updated_at,
        ),
        document=None
        if document is None
        else ExtractionDocumentSummary(
            id=document.id,
            title=document.title,
            extractor_type=document.extractor_type,
            extractor_version=document.extractor_version,
            status=document.status,
            plain_text=document.plain_text,
            content_hash=document.content_hash,
            metadata_json=document.metadata_json,
            error_code=document.error_code,
            error_message=document.error_message,
            created_at=document.created_at,
        ),
        chunks=[
            ChunkSummary(
                id=chunk.id,
                sequence=chunk.sequence,
                heading_path=chunk.heading_path,
                chunk_type=chunk.chunk_type,
                content=chunk.content,
                char_count=chunk.char_count,
                token_count=chunk.token_count,
            )
            for chunk in chunks
        ],
    )


@router.post("/sources/{source_id}/extract", response_model=ExtractionView)
def extract_source(
    source_id: uuid.UUID,
    service: ExtractionService = Depends(get_extraction_service),
) -> ExtractionView:
    try:
        service.schedule(source_id, ExtractionTrigger.MANUAL.value, force=False)
    except LookupError:
        return JSONResponse(status_code=404, content={"code": "SOURCE_NOT_FOUND", "message": "找不到该资料。"})
    except RuntimeError:
        return JSONResponse(status_code=409, content={"code": "EXTRACTION_IN_PROGRESS", "message": "提取仍在进行。"})
    run, document, chunks = service.current_view(source_id)
    return _view(run, document, chunks)


@router.post("/sources/{source_id}/reextract", response_model=ExtractionView)
def reextract_source(
    source_id: uuid.UUID,
    service: ExtractionService = Depends(get_extraction_service),
) -> ExtractionView:
    try:
        service.schedule(source_id, ExtractionTrigger.REEXTRACT.value, force=True)
    except LookupError:
        return JSONResponse(status_code=404, content={"code": "SOURCE_NOT_FOUND", "message": "找不到该资料。"})
    except RuntimeError:
        return JSONResponse(status_code=409, content={"code": "EXTRACTION_IN_PROGRESS", "message": "提取仍在进行。"})
    run, document, chunks = service.current_view(source_id)
    return _view(run, document, chunks)


@router.get("/sources/{source_id}/extraction", response_model=ExtractionView)
def get_extraction(
    source_id: uuid.UUID,
    service: ExtractionService = Depends(get_extraction_service),
) -> ExtractionView:
    run, document, chunks = service.current_view(source_id)
    return _view(run, document, chunks)


@router.post("/sources/{source_id}/supplement", response_model=ExtractionView)
def add_user_text_supplement(
    source_id: uuid.UUID,
    body: UserTextSupplementBody,
    service: ExtractionService = Depends(get_extraction_service),
) -> ExtractionView:
    source = service.session.get(SourceItem, source_id)
    if source is None or not scope_visible_for_api(source.system_scope):
        return JSONResponse(status_code=404, content={"code": "SOURCE_NOT_FOUND", "message": "找不到该资料。"})
    try:
        service.add_user_text_supplement(source_id, body.text)
    except LookupError:
        return JSONResponse(status_code=404, content={"code": "SOURCE_NOT_FOUND", "message": "找不到该资料。"})
    except RuntimeError:
        return JSONResponse(status_code=409, content={"code": "EXTRACTION_IN_PROGRESS", "message": "提取仍在进行。"})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"code": str(exc), "message": "仅支持为 X/Twitter 帖子补充原文。"})
    run, document, chunks = service.current_view(source_id)
    return _view(run, document, chunks)
