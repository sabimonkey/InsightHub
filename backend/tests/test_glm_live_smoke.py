"""Optional live GLM smoke (paid). Run: INSIGHTHUB_LIVE_GLM=1 pytest tests/test_glm_live_smoke.py -q"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("INSIGHTHUB_LIVE_GLM") != "1", reason="Set INSIGHTHUB_LIVE_GLM=1 for paid live validation")


def test_live_glm_analysis_smoke(db_session, raw_root, tmp_path):
    """One isolated short-text analysis against production routing (USER scope must not be used)."""
    from app.core.config import get_settings
    from app.services.analysis.service import AnalysisService
    from app.services.extraction.service import ExtractionService
    from app.services.ingestion.service import IngestionService
    from app.services.system_scope import AUTOMATION_TEST_SCOPE

    settings = get_settings()
    if settings.llm_enable_fake:
        pytest.skip("Disable LLM_ENABLE_FAKE for live smoke")

    text = "Live smoke 2026-10-21: InsightHub validates GLM structured analysis with a short recorded sentence."
    ingest = IngestionService(db_session, raw_root, max_upload_size_bytes=50_000)
    created = ingest.ingest_text(text, scope=AUTOMATION_TEST_SCOPE)
    ExtractionService(
        db_session,
        raw_root,
        tmp_path / "live_extract",
        inline=True,
        chunk_max_chars=800,
        chunk_overlap_chars=0,
        max_pdf_pages=1,
        web_timeout=1,
        web_max_bytes=1000,
        web_max_redirects=1,
    ).schedule(created.source_item.id, "MANUAL", force=True)

    run = AnalysisService(db_session, inline=True, settings=settings).start(created.source_item.id)
    assert run.provider_type == "ZAI"
    assert run.status in {"SUCCEEDED", "PARTIAL"}, (run.status, run.error_code, run.error_message)
    assert run.output_tokens is not None
    assert uuid.UUID(str(run.id))
