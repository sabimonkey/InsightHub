"""M-PIPELINE-R3: worker guard, cover retry, analysis backfill preview."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.services.cover.service import CoverServiceError, CoverGenerationService
from app.services.jobs.runtime_guard import WorkerNotAvailableError, ensure_async_worker
from app.services.pipeline.analysis_batch import preview_analysis_backfill


def test_ensure_async_worker_raises_when_no_worker(monkeypatch):
    monkeypatch.setattr("app.services.jobs.runtime_guard.worker_detected", lambda *_a, **_k: False)
    with pytest.raises(WorkerNotAvailableError) as exc:
        ensure_async_worker(inline=False)
    assert exc.value.code == "WORKER_NOT_CONSUMING"


def test_ensure_async_worker_inline_skips(monkeypatch):
    monkeypatch.setattr("app.services.jobs.runtime_guard.worker_detected", lambda *_a, **_k: False)
    ensure_async_worker(inline=True)


def test_preview_analysis_backfill_empty_db(db_session: Session):
    body = preview_analysis_backfill(db_session)
    assert "default_candidate_count" in body
    assert "buckets" in body


def test_cover_retry_not_found(db_session: Session):
    import uuid

    service = CoverGenerationService(db_session)
    with pytest.raises(CoverServiceError) as exc:
        service.retry_failed_run(uuid.uuid4(), confirm_send=True)
    assert exc.value.code == "RUN_NOT_FOUND"
