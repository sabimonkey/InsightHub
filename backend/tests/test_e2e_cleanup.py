import uuid

import pytest
from sqlalchemy import select

from app.models.extraction import ContentChunk, ExtractedDocument, ExtractionRun
from app.models.source_item import SourceItem
from tests.e2e_cleanup import JobsNotTerminalError, ProtectedSourceError, purge_markers

PROTECTED = "https://x.com/ai_suxiaole/status/2106663866235261360"


def _source(display_name: str, *, canonical_url: str | None = None) -> SourceItem:
    return SourceItem(
        id=uuid.uuid4(),
        source_type="URL" if canonical_url else "TEXT",
        original_url=canonical_url,
        canonical_url=canonical_url,
        display_name=display_name,
        content_hash=None if canonical_url else uuid.uuid4().hex,
        status="STORED",
    )


def test_cleanup_removes_extraction_chain_and_is_idempotent(db_session):
    source = _source(f"e2e-cleanup-{uuid.uuid4()}")
    run = ExtractionRun(id=uuid.uuid4(), source_item_id=source.id, status="SUCCEEDED", trigger="AUTO", is_current=True)
    document = ExtractedDocument(
        id=uuid.uuid4(),
        extraction_run_id=run.id,
        source_item_id=source.id,
        extractor_type="text",
        extractor_version="test",
        status="SUCCEEDED",
        plain_text="owned sentence",
        metadata_json={},
        content_hash="abc",
    )
    chunk = ContentChunk(
        id=uuid.uuid4(),
        extracted_document_id=document.id,
        sequence=0,
        chunk_type="paragraph",
        content="owned sentence",
        char_count=14,
        metadata_json={},
    )
    db_session.add(source)
    db_session.flush()
    db_session.add(run)
    db_session.flush()
    db_session.add(document)
    db_session.flush()
    db_session.add(chunk)
    db_session.flush()

    purge_markers(db_session, [source.display_name], commit=False, timeout_seconds=0)
    assert db_session.get(SourceItem, source.id) is None
    assert db_session.get(ExtractionRun, run.id) is None
    assert db_session.get(ExtractedDocument, document.id) is None
    assert db_session.get(ContentChunk, chunk.id) is None

    purge_markers(db_session, [source.display_name], commit=False, timeout_seconds=0)
    assert db_session.get(SourceItem, source.id) is None


def test_cleanup_leaves_real_sources_and_refuses_protected_urls(db_session):
    real = db_session.scalar(select(SourceItem).where(SourceItem.canonical_url == PROTECTED))
    assert real is not None
    owned = _source(f"e2e-cleanup-{uuid.uuid4()}")
    db_session.add(owned)
    db_session.flush()

    purge_markers(db_session, [owned.display_name], commit=False, timeout_seconds=0)

    assert db_session.get(SourceItem, owned.id) is None
    assert db_session.get(SourceItem, real.id) is not None
    with pytest.raises(ProtectedSourceError):
        purge_markers(db_session, [PROTECTED], commit=False, timeout_seconds=0)
    assert db_session.get(SourceItem, real.id) is not None


def test_cleanup_does_not_delete_while_extraction_is_running(db_session):
    source = _source(f"e2e-cleanup-{uuid.uuid4()}")
    run = ExtractionRun(id=uuid.uuid4(), source_item_id=source.id, status="RUNNING", trigger="AUTO", is_current=False)
    db_session.add(source)
    db_session.flush()
    db_session.add(run)
    db_session.flush()

    with pytest.raises(JobsNotTerminalError):
        purge_markers(db_session, [source.display_name], commit=False, timeout_seconds=0)

    assert db_session.get(SourceItem, source.id) is not None
    assert db_session.get(ExtractionRun, run.id) is not None
