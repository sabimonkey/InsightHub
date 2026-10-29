import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.extraction import ContentChunk, ExtractedDocument, ExtractionRun
from app.models.ingestion_record import IngestionRecord
from app.models.source_item import SourceItem
from app.services.analysis.service import AnalysisError, AnalysisService
from app.services.extraction.service import ExtractionService
from app.services.extraction_status import extraction_status_for_source


def _service(db_session, raw_root, tmp_path):
    settings = get_settings()
    return ExtractionService(
        db_session,
        raw_root,
        tmp_path / "extracted",
        inline=True,
        chunk_max_chars=800,
        chunk_overlap_chars=0,
        max_pdf_pages=1,
        web_timeout=1,
        web_max_bytes=1000,
        web_max_redirects=1,
    )


def _x_source(db_session):
    now = datetime.now(timezone.utc)
    url = f"https://x.com/testuser/status/{uuid.uuid4().int % 10**18:018d}?s=46"
    source = SourceItem(
        id=uuid.uuid4(),
        source_type="URL",
        original_url=url,
        canonical_url=url.split("?", 1)[0],
        display_name=url.split("?", 1)[0],
        status="STORED",
        privacy_level="PRIVATE",
        system_scope="AUTOMATION_TEST",
        created_at=now,
        updated_at=now,
    )
    db_session.add(source)
    db_session.commit()
    return source


def test_user_paste_is_saved_as_new_auditable_extraction_version(db_session, raw_root, tmp_path):
    source = _x_source(db_session)
    text = "The user supplied the original X post text after the linked article could not be reached."
    run = _service(db_session, raw_root, tmp_path).add_user_text_supplement(source.id, text)
    doc = db_session.scalar(select(ExtractedDocument).where(ExtractedDocument.extraction_run_id == run.id))
    record = db_session.scalar(select(IngestionRecord).where(IngestionRecord.source_item_id == source.id))
    chunk = db_session.scalar(select(ContentChunk).where(ContentChunk.extracted_document_id == doc.id))

    assert run.trigger == "USER_SUPPLEMENT"
    assert run.status == "SUCCEEDED"
    assert doc.plain_text == text
    assert doc.metadata_json["provenance"] == "USER_PROVIDED"
    assert chunk.metadata_json["provenance"] == "USER_PROVIDED"
    assert record.ingestion_type == "TEXT_SUPPLEMENT"
    assert record.origin == "USER_PROVIDED"


def test_x_metadata_only_source_cannot_enter_analysis_until_supplemented(db_session):
    source = _x_source(db_session)
    now = datetime.now(timezone.utc)
    extraction = ExtractionRun(
        id=uuid.uuid4(), source_item_id=source.id, status="PARTIAL", trigger="REEXTRACT",
        extractor_type="WEB", extractor_version="web-v1", is_current=True,
        created_at=now, updated_at=now,
    )
    db_session.add(extraction)
    db_session.flush()
    doc = ExtractedDocument(
        id=uuid.uuid4(), extraction_run_id=extraction.id, source_item_id=source.id,
        source_asset_id=None, extractor_type="WEB", extractor_version="web-v1", status="PARTIAL",
        title="Second Brain", plain_text="How to build a Second Brain that actually does the work",
        structured_text="[]", language="en", metadata_json={"content_completeness":"metadata_only"},
        content_hash="a" * 64, error_code="X_METADATA_ONLY", error_message="metadata only",
        created_at=now, updated_at=now,
    )
    db_session.add(doc)
    db_session.commit()

    status = extraction_status_for_source(db_session, source.id)
    assert status["has_usable_content"] is False

    with pytest.raises(AnalysisError) as caught:
        AnalysisService(db_session, inline=True, settings=get_settings())._inputs(source.id)
    assert caught.value.code == "SOURCE_CONTENT_INCOMPLETE"
