import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.ingestion_record import IngestionRecord
from app.models.source_item import SourceItem
from app.services.retrieval.search import SearchService
from app.services.source_lifecycle import restore_source, soft_delete_source, trash_cutoff
from app.services.synthesis.service import SynthesisService


@pytest.fixture
def collected_source(db_session, raw_root):
    from app.services.ingestion.service import IngestionService

    service = IngestionService(db_session, raw_root, max_upload_size_bytes=65536)
    record = service.ingest_text("软删除测试资料 Trash Test")
    db_session.commit()
    return record.source_item.id


def test_soft_delete_hides_from_library_query(db_session, collected_source):
    soft_delete_source(db_session, collected_source)
    visible = db_session.scalar(select(SourceItem.id).where(SourceItem.id == collected_source, SourceItem.deleted_at.is_(None)))
    assert visible is None


def test_restore_within_seven_days(db_session, collected_source):
    soft_delete_source(db_session, collected_source)
    restore_source(db_session, collected_source)
    row = db_session.get(SourceItem, collected_source)
    assert row is not None and row.deleted_at is None


def test_search_excludes_deleted(db_session, collected_source):
    soft_delete_source(db_session, collected_source)
    rows = SearchService(db_session)._scope_sources({"scope": "mine"})
    assert all(str(item["id"]) != str(collected_source) for item in rows)


def test_brief_selection_excludes_deleted(db_session, collected_source):
    today = datetime.now(timezone.utc).date().isoformat()
    soft_delete_source(db_session, collected_source)
    preview = SynthesisService(db_session).preview(
        {"start_date": today, "end_date": today, "date_basis": "COLLECTED_AT", "category_slugs": [], "topic_ids": []}
    )
    ids = {str(row["source_id"]) for row in preview["sources"]}
    assert str(collected_source) not in ids


def test_trash_expired_restore(db_session, collected_source):
    soft_delete_source(db_session, collected_source)
    row = db_session.get(SourceItem, collected_source)
    row.deleted_at = trash_cutoff() - timedelta(days=1)
    db_session.commit()
    from app.services.source_lifecycle import SourceLifecycleError

    with pytest.raises(SourceLifecycleError) as exc:
        restore_source(db_session, collected_source)
    assert exc.value.code == "TRASH_EXPIRED"
