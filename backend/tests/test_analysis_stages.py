import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.extraction import ContentChunk
from app.services.analysis.service import AnalysisService
from app.services.analysis.stages import STAGE_FAILED, STAGE_QUEUED, STAGE_SUCCEEDED, read_stage
from app.services.extraction.service import ExtractionService
from app.services.ingestion.service import IngestionService
from app.services.llm.provider import FakeLLMProvider


def _settings():
    from app.core.config import Settings

    return Settings(
        llm_enable_fake=True,
        llm_default_provider="FAKE",
        default_llm_context_window=8000,
        analysis_max_output_tokens=200,
        max_evidence_quote_chars=500,
        analysis_output_language="auto",
    )


def _prepare(db_session, raw_root, tmp_path, text: str):
    ingest = IngestionService(db_session, raw_root, max_upload_size_bytes=200_000)
    created = ingest.ingest_text(text)
    extraction = ExtractionService(
        db_session,
        raw_root,
        tmp_path / "extracted",
        inline=True,
        chunk_max_chars=500,
        chunk_overlap_chars=20,
        max_pdf_pages=2,
        web_timeout=1,
        web_max_bytes=1000,
        web_max_redirects=1,
    )
    extraction.schedule(created.source_item.id, "MANUAL", force=True)
    return created


def test_analysis_stage_progression(db_session, raw_root, tmp_path):
    created = _prepare(db_session, raw_root, tmp_path, "recorded fact sentence")
    from app.models.extraction import ExtractedDocument

    doc = db_session.scalar(select(ExtractedDocument).where(ExtractedDocument.source_item_id == created.source_item.id))
    chunk = db_session.scalar(select(ContentChunk).where(ContentChunk.extracted_document_id == doc.id).limit(1))
    good_payload = json.dumps(
        {
            "summary": "阶段测试摘要",
            "facts": [{"text": "recorded fact sentence", "evidence": [{"chunk_id": str(chunk.id), "quote": "recorded fact sentence"}]}],
            "source_claims": [],
            "inferences": [],
            "hypotheses": [],
            "unknowns": [],
            "questions": [],
            "category_candidates": [],
            "topic_candidates": [],
            "entities": [],
        },
        ensure_ascii=False,
    )
    service = AnalysisService(db_session, inline=True, settings=_settings(), providers={"FAKE": FakeLLMProvider(script=[good_payload])})
    run = service.start(created.source_item.id)
    assert read_stage(run) in {STAGE_QUEUED, STAGE_SUCCEEDED}
    assert run.status in {"SUCCEEDED", "PARTIAL"}
    assert read_stage(run) == STAGE_SUCCEEDED


def test_get_analysis_prefers_active_run(db_session, raw_root, tmp_path):
    created = _prepare(db_session, raw_root, tmp_path, "recorded fact sentence")
    from app.models.analysis import AnalysisRun
    from app.models.extraction import ExtractedDocument

    doc = db_session.scalar(select(ExtractedDocument).where(ExtractedDocument.source_item_id == created.source_item.id))
    chunk = db_session.scalar(select(ContentChunk).where(ContentChunk.extracted_document_id == doc.id).limit(1))
    good_payload = json.dumps(
        {
            "summary": "保留摘要",
            "facts": [{"text": "recorded fact sentence", "evidence": [{"chunk_id": str(chunk.id), "quote": "recorded fact sentence"}]}],
            "source_claims": [],
            "inferences": [],
            "hypotheses": [],
            "unknowns": [],
            "questions": [],
            "category_candidates": [],
            "topic_candidates": [],
            "entities": [],
        },
        ensure_ascii=False,
    )
    service = AnalysisService(db_session, inline=True, settings=_settings(), providers={"FAKE": FakeLLMProvider(script=[good_payload])})
    service.start(created.source_item.id)
    pending = AnalysisRun(
        id=uuid.uuid4(),
        source_item_id=created.source_item.id,
        extracted_document_id=doc.id,
        provider_type="FAKE",
        model_name="fake",
        prompt_name="source_analysis",
        prompt_version="1.1.0",
        status="PENDING",
        is_current=False,
        metadata_json={"stage": STAGE_QUEUED},
        created_at=datetime.now(timezone.utc) + timedelta(seconds=30),
    )
    db_session.add(pending)
    db_session.commit()
    _, _, _, _, _, _ = service.view(created.source_item.id)
    run, *_ = service.view(created.source_item.id)
    assert run.id == pending.id
    assert run.status == "PENDING"
    assert read_stage(run) == STAGE_QUEUED


def test_historical_run_with_non_object_metadata_stays_readable(db_session):
    from types import SimpleNamespace

    legacy_run = SimpleNamespace(metadata_json=["legacy", "metadata"], status="FAILED")
    assert read_stage(legacy_run) == STAGE_FAILED
