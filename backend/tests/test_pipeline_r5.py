"""M-PIPELINE-R5: 503 backoff, concurrency gate, batch modes, analysis idempotency."""

from __future__ import annotations

import httpx
import pytest

from app.services.llm.provider import OpenAICompatibleProvider
from app.services.llm.types import LLMError, LLMRequest
from app.services.llm.retry_policy import sleep_before_retry
from app.services.pipeline.analysis_batch import preview_analysis_backfill


def test_sleep_before_retry_does_not_crash():
    sleep_before_retry(attempt=0, status_code=503, retry_after_header=None)


def test_provider_retries_503_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="unavailable", headers={"retry-after": "0"})
        return httpx.Response(
            200,
            json={
                "model": "m",
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    monkeypatch.setattr("app.services.llm.retry_policy.time.sleep", lambda *_a, **_k: None)
    provider = OpenAICompatibleProvider(
        provider_type="SILICONFLOW",
        base_url="https://example.test/v1",
        model="m",
        api_key="k",
        is_local=False,
        timeout=1,
        max_retries=2,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    out = provider.complete(LLMRequest("s", "u", None, 0, 16, {}))
    assert out.text == "ok"
    assert calls["n"] == 2


def test_provider_maps_503_to_overloaded():
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="unavailable")

    provider = OpenAICompatibleProvider(
        provider_type="SILICONFLOW",
        base_url="https://example.test/v1",
        model="m",
        api_key="k",
        is_local=False,
        timeout=1,
        max_retries=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(LLMError) as exc:
        provider.complete(LLMRequest("s", "u", None, 0, 16, {}))
    assert exc.value.code == "PROVIDER_OVERLOADED"
    assert calls["n"] == 1


def test_analysis_start_rejects_duplicate_active(db_session, raw_root, tmp_path):
    from app.core.config import Settings
    from app.services.analysis.service import AnalysisError, AnalysisService
    from app.services.extraction.service import ExtractionService
    from app.services.ingestion.service import IngestionService
    from app.services.llm.provider import FakeLLMProvider

    ingest = IngestionService(db_session, raw_root, max_upload_size_bytes=50_000)
    created = ingest.ingest_text("duplicate active guard sentence")
    ExtractionService(
        db_session,
        raw_root,
        tmp_path / "ex",
        inline=True,
        chunk_max_chars=400,
        chunk_overlap_chars=0,
        max_pdf_pages=1,
        web_timeout=1,
        web_max_bytes=1000,
        web_max_redirects=1,
    ).schedule(created.source_item.id, "MANUAL", force=True)
    settings = Settings(llm_enable_fake=True, llm_default_provider="FAKE", analysis_max_output_tokens=200)
    service = AnalysisService(db_session, inline=False, settings=settings, providers={"FAKE": FakeLLMProvider()}, enqueue=lambda *_a, **_k: None)
    service.start(created.source_item.id)
    with pytest.raises(AnalysisError) as exc:
        service.start(created.source_item.id)
    assert exc.value.code == "ANALYSIS_ALREADY_RUNNING"


def test_batch_preview_splits_fresh_and_retry(db_session):
    body = preview_analysis_backfill(db_session)
    assert "fresh_candidate_count" in body
    assert "retry_failed_count" in body
    assert "active_task_count" in body
    assert body["default_candidate_count"] == body["fresh_candidate_count"]
