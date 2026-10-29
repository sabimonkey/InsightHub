import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import Settings
from app.models.extraction import ContentChunk
from app.models.source_item import SourceItem
from app.services.analysis.schema import parse_analysis
from app.services.analysis.service import AnalysisService
from app.services.extraction.service import ExtractionService
from app.services.ingestion.service import IngestionService
from app.services.llm.provider import FakeLLMProvider
from app.services.research_note import analysis_status_for_source, build_research_note, research_note_markdown
from app.services.research_note_projection import present_source_claim, project_research_note_reading, research_note_markdown_from_note
from types import SimpleNamespace


def test_research_note_markdown_sections():
    note = {
        "title": "标题",
        "collected_at": "2026-10-13T00:00:00+00:00",
        "reading": {
            "core_summary": {"paragraphs": ["摘要段落"]},
            "core_points": ["事实 A"],
            "inferences_and_open": None,
            "source_and_evidence": {
                "source_type_label": "网页",
                "author": None,
                "collected_at": None,
                "original_url": "https://example.com/x",
                "evidence_summary": {"verified_count": 0, "items": []},
            },
        },
        "analysis": {"provider": "DeepSeek", "model_name": "deepseek-v4-pro", "prompt_name": "source_analysis", "prompt_version": "1.1.0"},
    }
    md = research_note_markdown(note)
    assert "# 标题" in md
    assert "## 核心摘要" in md
    assert "## 核心要点" in md
    assert "事实 A" in md
    assert "https://example.com/x" in md
    assert "AI 分析" in md


def test_projection_core_summary_keeps_attribution():
    presented = present_source_claim("OpenKB 可以识别资料之间的矛盾。", "URL")
    assert "网页介绍称" in presented or "帖子介绍称" in presented
    claims = [
        SimpleNamespace(id=uuid.uuid4(), claim_type="SOURCE_CLAIM", text="OpenKB 可以识别资料之间的矛盾。", importance=1, sequence=0),
    ]
    reading = project_research_note_reading(
        summary="这篇帖子主要介绍 OpenKB。",
        claims=claims,
        evidence_by_claim={},
        source_type="URL",
        source_type_label="网页",
        author=None,
        collected_at=None,
        original_url="https://example.com",
        canonical_url=None,
    )
    assert reading["core_summary"]["paragraphs"] == ["这篇帖子主要介绍 OpenKB。"]
    assert any("介绍称" in point for point in reading["core_points"])


def test_projection_core_points_dedupes_fact_and_source_claim():
    fact_id = uuid.uuid4()
    claims = [
        SimpleNamespace(id=fact_id, claim_type="FACT", text="OpenKB 支持 PDF 导入。", importance=2, sequence=0),
        SimpleNamespace(id=uuid.uuid4(), claim_type="SOURCE_CLAIM", text="OpenKB 支持 PDF 导入。", importance=1, sequence=1),
    ]
    reading = project_research_note_reading(
        summary=None,
        claims=claims,
        evidence_by_claim={},
        source_type="URL",
        source_type_label="网页",
        author=None,
        collected_at=None,
        original_url=None,
        canonical_url=None,
    )
    assert len(reading["core_points"]) == 1


def test_projection_hides_default_open_questions():
    claims = [
        SimpleNamespace(id=uuid.uuid4(), claim_type="INFERENCE", text="产品思路更接近知识库。", importance=1, sequence=0),
        SimpleNamespace(id=uuid.uuid4(), claim_type="QUESTION", text="这些网站是否安全", importance=None, sequence=1),
    ]
    reading = project_research_note_reading(
        summary="x",
        claims=claims,
        evidence_by_claim={},
        source_type="TEXT",
        source_type_label="文本",
        author=None,
        collected_at=None,
        original_url=None,
        canonical_url=None,
    )
    assert reading["inferences_and_open"] is None


def test_projection_meta_noise_filtered_from_points():
    claims = [
        SimpleNamespace(id=uuid.uuid4(), claim_type="FACT", text="该帖获得 1200 次浏览和 300 个点赞。", importance=2, sequence=0),
        SimpleNamespace(id=uuid.uuid4(), claim_type="FACT", text="Z-Library 提供电子书检索。", importance=2, sequence=1),
    ]
    reading = project_research_note_reading(
        summary="汇总了一批实用网站。",
        claims=claims,
        evidence_by_claim={},
        source_type="URL",
        source_type_label="网页",
        author=None,
        collected_at=None,
        original_url=None,
        canonical_url=None,
    )
    joined = " ".join(reading["core_points"])
    assert "浏览" not in joined
    assert "Z-Library" in joined or any("Z-Library" in item["text"] for item in (reading.get("core_content") or {}).get("items", []))


def test_projection_hides_empty_inference_section():
    claims = [SimpleNamespace(id=uuid.uuid4(), claim_type="FACT", text="仅事实。", importance=1, sequence=0)]
    reading = project_research_note_reading(
        summary="摘要",
        claims=claims,
        evidence_by_claim={},
        source_type="TEXT",
        source_type_label="文本",
        author=None,
        collected_at=None,
        original_url=None,
        canonical_url=None,
    )
    assert reading["inferences_and_open"] is None


def test_markdown_export_parity_with_reading():
    note = {
        "title": "导出标题",
        "collected_at": "2026-10-13T00:00:00+00:00",
        "reading": {
            "core_summary": {"paragraphs": ["摘要"]},
            "core_points": ["要点一"],
            "inferences_and_open": None,
            "source_and_evidence": {
                "source_type_label": "文本",
                "author": "作者",
                "collected_at": None,
                "original_url": "https://example.com/a",
                "evidence_summary": {"verified_count": 0, "items": []},
            },
        },
        "analysis": {},
    }
    md = research_note_markdown_from_note(note)
    assert "## 核心摘要" in md
    assert "## 核心要点" in md
    assert "## 来源与依据" in md


def test_unanalyzed_source_note(db_session):
    source = SourceItem(id=uuid.uuid4(), source_type="TEXT", display_name="pending", status="STORED", system_scope="USER")
    db_session.add(source)
    db_session.commit()
    label, code = analysis_status_for_source(db_session, source.id)
    assert label == "未分析"
    assert code is None
    note = build_research_note(db_session, source.id, Settings())
    assert note["analysis_status"] == "未分析"


def _settings():
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


def test_failed_analysis_shows_failed_not_unanalyzed(db_session, raw_root, tmp_path):
    created = _prepare(db_session, raw_root, tmp_path, "recorded fact sentence")
    failed = AnalysisService(db_session, inline=True, settings=_settings(), providers={"FAKE": FakeLLMProvider(script=["not json", "still bad"])}).start(
        created.source_item.id
    )
    assert failed.status == "FAILED"
    label, code = analysis_status_for_source(db_session, created.source_item.id)
    assert label == "分析失败"
    assert code == "FAILED"
    note = build_research_note(db_session, created.source_item.id, _settings())
    assert note["analysis_status"] == "分析失败"
    assert note["analysis_failure"]["error_code"] == "STRUCTURED_OUTPUT_INVALID"


def test_prior_note_kept_when_reanalysis_fails(db_session, raw_root, tmp_path):
    created = _prepare(db_session, raw_root, tmp_path, "recorded fact sentence")
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
    AnalysisService(db_session, inline=True, settings=_settings(), providers={"FAKE": FakeLLMProvider(script=["not json", "still bad"])}).start(
        created.source_item.id
    )
    note = build_research_note(db_session, created.source_item.id, _settings())
    assert note["summary"] == "保留摘要"
    assert note["analysis_failure"]["supersedes_content"] is True
    assert note["analysis_status_code"] == "SUCCEEDED"


def test_parse_analysis_tolerates_extra_fields_and_long_summary():
    payload = {
        "summary": "x" * 500,
        "facts": [],
        "source_claims": [],
        "inferences": [],
        "hypotheses": [],
        "unknowns": [],
        "questions": [],
        "category_candidates": [],
        "topic_candidates": [],
        "entities": [],
        "unknowns_and_questions": ["q1"],
        "extra_field": "drop me",
    }
    parsed = parse_analysis(json.dumps(payload, ensure_ascii=False))
    assert len(parsed.summary) <= 400
    assert parsed.questions == ["q1"]
