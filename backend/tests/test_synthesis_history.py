import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.synthesis import clear_brief_history, delete_brief, get_brief, list_briefs
from app.jobs.synthesis import synthesis_job_failed
from app.models.synthesis import Brief, BriefSource
from app.services.ingestion.service import IngestionService


def _brief(db_session, *, status="SUCCEEDED", completed_at=None, scope="AUTOMATION_TEST", parent=None):
    now = datetime.now(timezone.utc)
    row = Brief(
        id=uuid.uuid4(),
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 28),
        date_basis="COLLECTED_AT",
        detail_level="STANDARD",
        status=status,
        prompt_name="brief-general",
        prompt_version="1.0.0",
        filters_json={"category_slugs": [], "topic_ids": []},
        exclusion_reasons_json={},
        structured_result_json={},
        regenerated_from_id=parent,
        system_scope=scope,
        created_at=now,
        completed_at=completed_at,
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_brief_history_orders_completed_notes_newest_first(db_session):
    now = datetime.now(timezone.utc)
    older = _brief(db_session, completed_at=now - timedelta(days=2))
    newest = _brief(db_session, completed_at=now)
    same_time = _brief(db_session, status="PARTIAL", completed_at=now)
    pending = _brief(db_session, status="PENDING")
    db_session.commit()

    result = list_briefs(db_session)

    ids = [str(item["id"]) for item in result["briefs"]]
    assert ids.index(str(newest.id)) < ids.index(str(older.id))
    assert ids.index(str(same_time.id)) < ids.index(str(pending.id))


def test_brief_delete_removes_only_note_history_and_keeps_source(db_session, raw_root):
    source = IngestionService(db_session, raw_root, max_upload_size_bytes=1024).ingest_text("preserved source body").source_item
    row = _brief(db_session)
    db_session.add(
        BriefSource(
            id=uuid.uuid4(),
            brief_id=row.id,
            source_item_id=source.id,
            selection_reason="IN_RANGE",
            role="PRIMARY_SELECTED",
            included=True,
            collection_count=1,
        )
    )
    db_session.commit()

    result = delete_brief(row.id, db_session)
    repeated = delete_brief(row.id, db_session)

    assert result["deleted"] is True
    assert repeated == {"deleted": False, "id": str(row.id)}
    assert db_session.get(Brief, row.id) is None
    assert db_session.get(type(source), source.id) is not None
    assert not list(db_session.scalars(select(BriefSource).where(BriefSource.brief_id == row.id)))


def test_active_brief_cannot_be_deleted_or_cleared(db_session):
    row = _brief(db_session, status="RUNNING")
    db_session.commit()

    with pytest.raises(HTTPException) as delete_error:
        delete_brief(row.id, db_session)
    assert delete_error.value.status_code == 409
    with pytest.raises(HTTPException) as clear_error:
        clear_brief_history(db_session)
    assert clear_error.value.status_code == 409
    assert db_session.get(Brief, row.id).status == "RUNNING"


def test_clear_history_deletes_only_visible_notes(db_session, monkeypatch):
    isolated_scope = f"N{uuid.uuid4().hex[:31]}"
    monkeypatch.setattr("app.services.system_scope.api_visibility_filter", lambda column: column == isolated_scope)
    monkeypatch.setattr("app.services.system_scope.scope_visible_for_api", lambda value, settings=None: value == isolated_scope)
    test_row = _brief(db_session, scope=isolated_scope)
    user_row = _brief(db_session, scope="USER")
    db_session.commit()

    result = clear_brief_history(db_session)

    assert result["deleted_count"] == 1
    assert db_session.get(Brief, test_row.id) is None
    assert db_session.get(Brief, user_row.id) is not None


def test_clear_history_http_contract_and_scope_preserve_sources(client, db_session, raw_root):
    from app.models.source_item import SourceItem

    source = IngestionService(db_session, raw_root, max_upload_size_bytes=1024).ingest_text("preserved source body").source_item
    visible = _brief(db_session, scope="AUTOMATION_TEST")
    hidden = _brief(db_session, scope="USER")
    db_session.add(
        BriefSource(
            id=uuid.uuid4(),
            brief_id=visible.id,
            source_item_id=source.id,
            selection_reason="IN_RANGE",
            role="PRIMARY_SELECTED",
            included=True,
            collection_count=1,
        )
    )
    db_session.commit()

    response = client.delete("/api/briefs")
    repeated = client.delete("/api/briefs")
    wrong_method = client.put("/api/briefs")

    assert response.status_code == 200
    assert response.json()["deleted_count"] >= 1
    assert repeated.status_code == 200
    assert repeated.json() == {"deleted_count": 0}
    assert wrong_method.status_code == 405
    assert "delete" in client.get("/openapi.json").json()["paths"]["/api/briefs"]
    assert db_session.get(Brief, visible.id) is None
    assert db_session.get(Brief, hidden.id) is not None
    assert db_session.get(SourceItem, source.id) is not None


def test_clear_history_rolls_back_if_database_delete_fails(db_session, monkeypatch):
    row = _brief(db_session, scope="AUTOMATION_TEST")
    db_session.commit()
    original_execute = db_session.execute
    calls = 0

    def fail_after_first_delete(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("simulated database failure")
        return original_execute(*args, **kwargs)

    monkeypatch.setattr(db_session, "execute", fail_after_first_delete)
    with pytest.raises(RuntimeError, match="simulated database failure"):
        clear_brief_history(db_session)
    db_session.rollback()

    assert db_session.get(Brief, row.id) is not None


def test_stale_brief_poll_is_reconciled_to_terminal_failure(db_session, monkeypatch):
    row = _brief(db_session, status="RUNNING")
    row.created_at = datetime.now(timezone.utc) - timedelta(hours=1)
    row.filters_json = {"category_slugs": []}
    db_session.commit()
    monkeypatch.setenv("JOB_STALE_AFTER_SECONDS", "900")

    result = get_brief(row.id, db_session)

    assert result["status"] == "FAILED"
    assert result["error_code"] == "WORKER_INTERRUPTED"
    assert result["completed_at"] is not None
    assert db_session.get(Brief, row.id).status == "FAILED"


def test_rq_timeout_callback_persists_terminal_failure(db_session, monkeypatch):
    from rq.timeouts import JobTimeoutException

    row = _brief(db_session, status="RUNNING")
    db_session.commit()

    class _BorrowedSession:
        def __getattr__(self, name):
            return getattr(db_session, name)

        def close(self):
            pass

    monkeypatch.setattr("app.jobs.synthesis.get_sessionmaker", lambda: lambda: _BorrowedSession())
    job = SimpleNamespace(args=(str(row.id),), func_name="app.jobs.synthesis.execute_brief")

    synthesis_job_failed(job, None, JobTimeoutException, JobTimeoutException("timeout"), None)

    db_session.refresh(row)
    assert row.status == "FAILED"
    assert row.error_code == "JOB_TIMEOUT"
    assert row.completed_at is not None


def test_duplicate_worker_execution_does_not_reenter_running_brief(db_session):
    from app.services.synthesis.service import SynthesisService

    row = _brief(db_session, status="RUNNING")
    db_session.commit()
    service = SynthesisService(db_session)
    service._selection = lambda _filters: (_ for _ in ()).throw(AssertionError("active task must not execute twice"))

    result = service.execute_brief(row.id)

    assert result.status == "RUNNING"
