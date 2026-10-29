from app.models.ingestion_record import IngestionRecord
from app.models.source_asset import SourceAsset
from app.models.source_item import SourceItem
from app.schemas.ingestion import (
    AssetSummary,
    IngestResponse,
    IngestionSummary,
    SourceSummary,
)
from app.services.ingestion.errors import DUPLICATE_MESSAGE, STORED_MESSAGE
from app.services.ingestion.service import IngestResult


def source_summary(source: SourceItem) -> SourceSummary:
    return SourceSummary(
        id=source.id,
        source_type=source.source_type,
        display_name=source.display_name,
        original_url=source.original_url,
        canonical_url=source.canonical_url,
        content_hash=source.content_hash,
        status=source.status,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def ingestion_summary(record: IngestionRecord) -> IngestionSummary:
    return IngestionSummary(
        id=record.id,
        source_item_id=record.source_item_id,
        ingestion_type=record.ingestion_type,
        original_input=record.original_input,
        collected_at=record.collected_at,
        duplicate_detected=record.duplicate_detected,
        duplicate_reason=record.duplicate_reason,
        status=record.status,
        origin=record.origin,
        created_at=record.created_at,
    )


def asset_summary(asset: SourceAsset | None) -> AssetSummary | None:
    if asset is None:
        return None
    return AssetSummary(
        id=asset.id,
        original_filename=asset.original_filename,
        stored_path=asset.stored_path,
        mime_type=asset.mime_type,
        size_bytes=asset.size_bytes,
        sha256=asset.sha256,
    )


def ingest_response(result: IngestResult) -> IngestResponse:
    return IngestResponse(
        source=source_summary(result.source_item),
        ingestion=ingestion_summary(result.ingestion_record),
        asset=asset_summary(result.asset),
        duplicate_detected=result.duplicate_detected,
        duplicate_reason=result.duplicate_reason,
        message=DUPLICATE_MESSAGE if result.duplicate_detected else STORED_MESSAGE,
    )
