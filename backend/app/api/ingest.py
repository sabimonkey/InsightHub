from fastapi import APIRouter, Depends, File, UploadFile

from app.api.deps import get_extraction_service, get_ingestion_service
from app.api.presenters import ingest_response
from app.schemas.ingestion import (
    BatchIngestResponse,
    FileIngestResult,
    IngestResponse,
    TextIngestRequest,
    UrlIngestRequest,
)
from app.services.extraction.enums import ExtractionTrigger
from app.services.extraction.service import ExtractionService
from app.services.ingestion.errors import IngestionError
from app.services.ingestion.service import IngestResult, IngestionService


def _schedule(extraction: ExtractionService, result: IngestResult) -> None:
    if result.duplicate_detected:
        return
    try:
        extraction.schedule(result.source_item.id, ExtractionTrigger.AUTO.value, force=False)
    except Exception:
        return

router = APIRouter(prefix="/api", tags=["ingest"])


@router.post("/ingest/url", response_model=IngestResponse)
def ingest_url(
    body: UrlIngestRequest,
    service: IngestionService = Depends(get_ingestion_service),
    extraction: ExtractionService = Depends(get_extraction_service),
) -> IngestResponse:
    result = service.ingest_url(body.url)
    _schedule(extraction, result)
    return ingest_response(result)


@router.post("/ingest/text", response_model=IngestResponse)
def ingest_text(
    body: TextIngestRequest,
    service: IngestionService = Depends(get_ingestion_service),
    extraction: ExtractionService = Depends(get_extraction_service),
) -> IngestResponse:
    result = service.ingest_text(body.text)
    _schedule(extraction, result)
    return ingest_response(result)


@router.post("/ingest/file", response_model=IngestResponse)
def ingest_file(
    file: UploadFile = File(...),
    service: IngestionService = Depends(get_ingestion_service),
    extraction: ExtractionService = Depends(get_extraction_service),
) -> IngestResponse:
    result = service.ingest_file(file.filename, file.file, file.content_type)
    _schedule(extraction, result)
    return ingest_response(result)


@router.post("/ingest/files", response_model=BatchIngestResponse)
def ingest_files(
    files: list[UploadFile] = File(...),
    service: IngestionService = Depends(get_ingestion_service),
    extraction: ExtractionService = Depends(get_extraction_service),
) -> BatchIngestResponse:
    if not files:
        raise IngestionError(400, "EMPTY_UPLOAD", "没有可上传的文件。")
    results: list[FileIngestResult] = []
    for upload in files:
        try:
            outcome = service.ingest_file(upload.filename, upload.file, upload.content_type)
        except IngestionError as exc:
            results.append(
                FileIngestResult(
                    filename=upload.filename,
                    ok=False,
                    code=exc.code,
                    message=exc.message,
                )
            )
            continue
        _schedule(extraction, outcome)
        results.append(
            FileIngestResult(
                filename=upload.filename,
                ok=True,
                message="已识别重复资料。已复用已有 Source。本次收集记录已保存。"
                if outcome.duplicate_detected
                else "资料已保存。",
                duplicate_detected=outcome.duplicate_detected,
                duplicate_reason=outcome.duplicate_reason,
                source_id=outcome.source_item.id,
                ingestion_id=outcome.ingestion_record.id,
            )
        )
    return BatchIngestResponse(results=results)
