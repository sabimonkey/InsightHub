import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class UrlIngestRequest(BaseModel):
    url: str


class TextIngestRequest(BaseModel):
    text: str


class AssetSummary(BaseModel):
    id: uuid.UUID
    original_filename: str
    stored_path: str
    mime_type: str
    size_bytes: int
    sha256: str


class SourceSummary(BaseModel):
    id: uuid.UUID
    source_type: str
    display_name: str | None
    original_url: str | None
    canonical_url: str | None
    content_hash: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class IngestionSummary(BaseModel):
    id: uuid.UUID
    source_item_id: uuid.UUID | None
    ingestion_type: str
    original_input: str
    collected_at: datetime
    duplicate_detected: bool
    duplicate_reason: str | None
    status: str
    origin: str = "USER_COLLECTION"
    created_at: datetime


class IngestResponse(BaseModel):
    source: SourceSummary
    ingestion: IngestionSummary
    asset: AssetSummary | None
    duplicate_detected: bool
    duplicate_reason: str | None
    message: str


class FileIngestResult(BaseModel):
    filename: str | None
    ok: bool
    code: str | None = None
    message: str | None = None
    duplicate_detected: bool = False
    duplicate_reason: str | None = None
    source_id: uuid.UUID | None = None
    ingestion_id: uuid.UUID | None = None


class BatchIngestResponse(BaseModel):
    results: list[FileIngestResult]


class InboxItem(BaseModel):
    ingestion_id: uuid.UUID
    source_id: uuid.UUID | None
    display_name: str | None
    source_type: str | None
    collected_at: datetime
    status: str
    duplicate_detected: bool
    duplicate_reason: str | None
    size_bytes: int | None
    original_url: str | None
    canonical_url: str | None
    original_filename: str | None
    extraction_status: str | None = None
    extraction_status_label: str | None = None
    extraction_status_code: str | None = None
    extraction_user_message: str | None = None
    has_usable_content: bool = False
    title: str | None = None
    analysis_status: str | None = None
    analysis_status_code: str | None = None
    summary_snippet: str | None = None


class InboxPage(BaseModel):
    items: list[InboxItem]
    page: int
    page_size: int
    total: int


class ChunkSummary(BaseModel):
    id: uuid.UUID
    sequence: int
    heading_path: list[str] | None
    chunk_type: str
    content: str
    char_count: int
    token_count: int | None


class ExtractionDocumentSummary(BaseModel):
    id: uuid.UUID
    title: str | None
    extractor_type: str
    extractor_version: str
    status: str
    plain_text: str
    content_hash: str
    metadata_json: dict
    error_code: str | None
    error_message: str | None
    created_at: datetime


class ExtractionRunSummary(BaseModel):
    id: uuid.UUID
    status: str
    trigger: str
    extractor_type: str | None
    extractor_version: str | None
    is_current: bool
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class ExtractionView(BaseModel):
    run: ExtractionRunSummary | None
    document: ExtractionDocumentSummary | None
    chunks: list[ChunkSummary]


class SourceDetail(BaseModel):
    source: SourceSummary
    asset: AssetSummary | None
    ingestions: list[IngestionSummary]
    extraction: ExtractionView | None = None


class ErrorBody(BaseModel):
    code: str
    message: str


class PageQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    filter: str = "all"
