"""Pipeline audit classification (AUTOMATION_TEST fixtures)."""

import uuid

from app.models.analysis import AnalysisResult, AnalysisRun, Claim, Evidence
from app.models.extraction import ContentChunk, ExtractedDocument, ExtractionRun
from app.models.source_item import SourceItem
from app.services.maintenance.pipeline_audit import audit_user_sources, classify_source


def _source(db_session, *, scope="AUTOMATION_TEST"):
    row = SourceItem(
        id=uuid.uuid4(),
        source_type="TEXT",
        display_name="audit-fixture",
        status="ACTIVE",
        system_scope=scope,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _extracted(db_session, source_id: uuid.UUID):
    run = ExtractionRun(
        id=uuid.uuid4(),
        source_item_id=source_id,
        status="SUCCEEDED",
        trigger="INGEST",
        is_current=True,
    )
    db_session.add(run)
    doc = ExtractedDocument(
        id=uuid.uuid4(),
        extraction_run_id=run.id,
        source_item_id=source_id,
        extractor_type="text",
        extractor_version="1",
        status="SUCCEEDED",
        plain_text="hello world " * 20,
        metadata_json={},
        content_hash="abc",
    )
    db_session.add(doc)
    chunk = ContentChunk(
        id=uuid.uuid4(),
        extracted_document_id=doc.id,
        sequence=0,
        chunk_type="paragraph",
        content="hello world " * 20,
        char_count=240,
        heading_path=[],
        metadata_json={},
    )
    db_session.add(chunk)
    db_session.commit()
    return run, doc, chunk


def test_classify_not_analyzed(db_session):
    source = _source(db_session)
    _extracted(db_session, source.id)
    row = classify_source(db_session, source.id)
    assert row.problem_class == "not_analyzed"
    assert row.taxonomy == "ANALYSIS_NOT_STARTED"


def test_classify_extraction_failed(db_session):
    source = _source(db_session)
    run = ExtractionRun(
        id=uuid.uuid4(),
        source_item_id=source.id,
        status="FAILED",
        trigger="INGEST",
        is_current=True,
        error_code="WEB_HTTP_ERROR",
    )
    db_session.add(run)
    db_session.commit()
    row = classify_source(db_session, source.id)
    assert row.problem_class == "extraction"


def test_audit_empty_user_scope(db_session):
    from app.core.config import get_settings

    out = audit_user_sources(db_session, get_settings())
    assert out["scope"] == "USER"
    assert out["source_total"] >= 0
