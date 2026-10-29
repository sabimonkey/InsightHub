from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import Settings
from app.models.analysis import AnalysisRun
from app.models.extraction import ContentChunk, ExtractedDocument
from app.services.analysis.service import AnalysisError, AnalysisService
from app.services.extraction.service import ExtractionService
from app.services.ingestion.service import IngestionService
from app.services.llm.provider import FakeLLMProvider
from app.services.maintenance.recovery import recover_stale_jobs


def _source(db_session, raw_root, tmp_path, text="The source says this claim is supported."):
    created = IngestionService(db_session, raw_root, max_upload_size_bytes=20_000).ingest_text(text)
    ExtractionService(
        db_session,
        raw_root,
        tmp_path / "extracted",
        inline=True,
        chunk_max_chars=500,
        chunk_overlap_chars=0,
        max_pdf_pages=2,
        web_timeout=1,
        web_max_bytes=1000,
        web_max_redirects=1,
    ).schedule(created.source_item.id, "MANUAL", force=True)
    return created.source_item


def _settings(**overrides):
    values = dict(llm_enable_fake=True, llm_default_provider="FAKE", analysis_max_output_tokens=200)
    values.update(overrides)
    return Settings(**values)


def _payload(db_session, source_id):
    doc = db_session.scalar(select(ExtractedDocument).where(ExtractedDocument.source_item_id == source_id))
    chunk = db_session.scalar(select(ContentChunk).where(ContentChunk.extracted_document_id == doc.id).limit(1))
    return json.dumps({
        "summary": "Evidence backed summary",
        "facts": [{"text": "The source says this claim is supported.", "evidence": [{"chunk_id": str(chunk.id), "quote": "The source says this claim is supported."}] }],
        "source_claims": [], "inferences": [], "hypotheses": [], "unknowns": [], "questions": [],
        "category_candidates": [], "topic_candidates": [], "entities": [],
    })


def test_fake_model_is_rejected_for_user_source(db_session, raw_root, tmp_path):
    source = _source(db_session, raw_root, tmp_path)
    source.system_scope = "USER"
    db_session.commit()
    service = AnalysisService(db_session, inline=True, settings=_settings(), providers={"FAKE": FakeLLMProvider()})
    try:
        service.start(source.id)
    except AnalysisError as exc:
        assert exc.code == "FAKE_PROVIDER_FORBIDDEN"
    else:
        raise AssertionError("FAKE must never be selected for a USER source")


def test_success_clears_stale_worker_error_and_records_simulated_provider(db_session, raw_root, tmp_path):
    source = _source(db_session, raw_root, tmp_path)
    service = AnalysisService(db_session, inline=False, settings=_settings(), providers={"FAKE": FakeLLMProvider(script=[_payload(db_session, source.id)])}, enqueue=lambda *_: None)
    run = service.start(source.id)
    run.error_code = "WORKER_NOT_CONSUMING"
    run.error_message = "historical queue warning"
    db_session.commit()

    completed = service.execute(run.id)
    assert completed.status == "SUCCEEDED"
    assert completed.error_code is None
    assert completed.error_message is None
    assert completed.provider_type == "FAKE"
    assert completed.model_name == "fake-model"
    assert completed.is_current


def test_stale_pending_run_cannot_be_started_by_late_worker(db_session, raw_root, tmp_path):
    source = _source(db_session, raw_root, tmp_path)
    fake = FakeLLMProvider()
    service = AnalysisService(db_session, inline=False, settings=_settings(), providers={"FAKE": fake}, enqueue=lambda *_: None)
    run = service.start(source.id)
    stale_now = datetime.now(timezone.utc) + timedelta(hours=1)
    recovery = recover_stale_jobs(db_session, _settings(job_stale_after_seconds=900), now=stale_now)
    assert any(item["id"] == str(run.id) and item.get("reason") == "stale_pending" for item in recovery["recovered"])

    result = service.execute(run.id)
    assert result.status == "FAILED"
    assert result.error_code == "WORKER_NOT_CONSUMING"
    assert fake.calls == []


def test_delayed_older_success_cannot_replace_newer_current_run(db_session, raw_root, tmp_path):
    source = _source(db_session, raw_root, tmp_path)
    doc = db_session.scalar(select(ExtractedDocument).where(ExtractedDocument.source_item_id == source.id))
    now = datetime.now(timezone.utc)
    older = AnalysisRun(id=uuid.uuid4(), source_item_id=source.id, extracted_document_id=doc.id,
                        provider_type="FAKE", model_name="fake-model", prompt_name="source_analysis",
                        prompt_version="1.1.0", status="SUCCEEDED", is_current=False,
                        metadata_json={}, created_at=now)
    newer = AnalysisRun(id=uuid.uuid4(), source_item_id=source.id, extracted_document_id=doc.id,
                        provider_type="FAKE", model_name="fake-model", prompt_name="source_analysis",
                        prompt_version="1.1.0", status="SUCCEEDED", is_current=True,
                        metadata_json={}, created_at=now + timedelta(seconds=1))
    db_session.add_all([older, newer])
    db_session.commit()

    service = AnalysisService(db_session, inline=True, settings=_settings())
    service._mark_current(older)
    db_session.commit()
    db_session.refresh(newer)
    assert newer.is_current
    assert not older.is_current


def test_user_research_note_does_not_trust_current_fake_run(db_session, raw_root, tmp_path):
    from app.services.research_note import build_research_note
    from app.services.synthesis.service import SynthesisService

    source = _source(db_session, raw_root, tmp_path)
    provider = FakeLLMProvider(script=[_payload(db_session, source.id)])
    run = AnalysisService(db_session, inline=True, settings=_settings(), providers={"FAKE": provider}).start(source.id)
    assert run.status == "SUCCEEDED"
    source.system_scope = "USER"
    db_session.commit()

    note = build_research_note(db_session, source.id, _settings())
    assert note["summary"] is None
    assert note["analysis_status_code"] == "FAKE_RESULT_UNTRUSTED"
    assert note["analysis"]["untrusted_for_user_research"]
    ready, reason = SynthesisService(db_session, _settings())._ready(source.id)
    assert not ready
    assert reason == "UNTRUSTED_FAKE_ANALYSIS"


def test_rq_analysis_enqueue_uses_run_id_and_bounded_timeout(monkeypatch):
    from app.jobs import analysis as analysis_job

    calls = {}

    class FakeQueue:
        def __init__(self, *_args, **_kwargs):
            pass

        def enqueue(self, func, *args, **kwargs):
            calls.update(func=func, args=args, kwargs=kwargs)
            return type("Job", (), {"id": kwargs["job_id"]})()

    monkeypatch.setattr(analysis_job, "Queue", FakeQueue)
    monkeypatch.setattr(analysis_job.Redis, "from_url", lambda *_: object())
    monkeypatch.setattr(analysis_job, "get_settings", lambda: Settings(analysis_job_timeout_seconds=600))

    assert analysis_job.enqueue_analysis("a-run-id") == "a-run-id"
    assert calls["args"] == ("a-run-id",)
    assert calls["kwargs"]["job_id"] == "a-run-id"
    assert calls["kwargs"]["job_timeout"] == 600


def test_automation_ingest_cannot_reuse_user_source(db_session, raw_root, monkeypatch):
    from app.core.config import get_settings
    from app.services.ingestion.errors import IngestionError

    body = f"scope separation test {uuid.uuid4()}"
    ingest = IngestionService(db_session, raw_root, max_upload_size_bytes=20_000)
    monkeypatch.setenv("INSIGHTHUB_SYSTEM_SCOPE", "USER")
    get_settings.cache_clear()
    original = ingest.ingest_text(body)
    assert original.source_item.system_scope == "USER"

    monkeypatch.setenv("INSIGHTHUB_SYSTEM_SCOPE", "AUTOMATION_TEST")
    get_settings.cache_clear()
    try:
        ingest.ingest_text(body)
    except IngestionError as exc:
        assert exc.code == "SOURCE_SCOPE_CONFLICT"
    else:
        raise AssertionError("automation data must not reuse a USER Source")
