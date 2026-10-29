"""R1-R1: visibility isolation uses system_scope only."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import Settings
from app.models.analysis import AnalysisResult, AnalysisRun, Claim
from app.models.enums import IngestionType
from app.models.extraction import ContentChunk
from app.models.ingestion_record import IngestionRecord
from app.models.organization import Category, SourceCategoryAssignment
from app.models.source_item import SourceItem
from app.services.extraction.service import ExtractionService
from app.services.ingestion.service import IngestionService
from app.services.retrieval.search import SearchService
from app.services.synthesis.service import SynthesisService
from app.services.system_scope import AUTOMATION_TEST_SCOPE, USER_SCOPE


def _settings(**kwargs) -> Settings:
    values = dict(
        llm_enable_fake=True,
        llm_default_provider="FAKE",
        insighthub_system_scope=USER_SCOPE,
        brief_inline=True,
    )
    values.update(kwargs)
    return Settings(**values)


def _category(db_session, slug: str) -> Category:
    row = db_session.scalar(select(Category).where(Category.slug == slug))
    assert row is not None
    return row


def _ready_source(db_session, raw_root, tmp_path, *, display_name: str, scope: str, text: str):
    created = IngestionService(db_session, raw_root, max_upload_size_bytes=200_000).ingest_text(text)
    source = created.source_item
    source.display_name = display_name
    source.system_scope = scope
    db_session.commit()
    ExtractionService(
        db_session,
        raw_root,
        tmp_path / "extracted",
        inline=True,
        chunk_max_chars=400,
        chunk_overlap_chars=0,
        max_pdf_pages=1,
        web_timeout=1,
        web_max_bytes=1000,
        web_max_redirects=1,
    ).schedule(source.id, "MANUAL", force=True)
    chunk = db_session.scalar(
        select(ContentChunk).join(ContentChunk.document).where(ContentChunk.document.has(source_item_id=source.id))
    )
    run = AnalysisRun(
        id=uuid.uuid4(),
        source_item_id=source.id,
        extracted_document_id=chunk.extracted_document_id,
        provider_type="FAKE",
        model_name="fake",
        prompt_name="source_analysis",
        prompt_version="1.0.0",
        status="SUCCEEDED",
        is_current=True,
        metadata_json={},
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(run)
    db_session.flush()
    result = AnalysisResult(
        id=uuid.uuid4(),
        analysis_run_id=run.id,
        summary="摘要",
        raw_structured_json={},
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(result)
    db_session.flush()
    claim = Claim(
        id=uuid.uuid4(),
        analysis_result_id=result.id,
        claim_type="FACT",
        text=text[:80],
        confidence=0.9,
        importance=3,
        sequence=1,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(claim)
    db_session.flush()
    cat = _category(db_session, "knowledge")
    now = datetime.now(timezone.utc)
    db_session.add(
        SourceCategoryAssignment(
            id=uuid.uuid4(),
            source_item_id=source.id,
            category_id=cat.id,
            origin="USER",
            status="ACTIVE",
            is_primary=True,
            confidence=0.9,
            reason="test",
            created_at=now,
            updated_at=now,
        )
    )
    db_session.add(
        IngestionRecord(
            id=uuid.uuid4(),
            source_item_id=source.id,
            ingestion_type=IngestionType.TEXT.value,
            original_input=text,
            collected_at=now,
            status="STORED",
        )
    )
    db_session.commit()
    return source


def _brief_titles(db_session, raw_root, tmp_path) -> set[str]:
    service = SynthesisService(db_session, _settings(), inline=True)
    preview = service.preview(
        {
            "start_date": "2020-01-01",
            "end_date": "2099-12-31",
            "date_basis": "COLLECTED_AT",
            "detail_level": "STANDARD",
            "category_slugs": ["knowledge"],
        }
    )
    return {row["title"] for row in preview["sources"]}


def test_automation_test_normal_title_hidden_from_user_brief(db_session, raw_root, tmp_path):
    _ready_source(
        db_session,
        raw_root,
        tmp_path,
        display_name="完全正常的真实标题",
        scope=AUTOMATION_TEST_SCOPE,
        text="automation scope isolation fact",
    )
    titles = _brief_titles(db_session, raw_root, tmp_path)
    assert "完全正常的真实标题" not in titles


def test_user_bench_r1_title_visible_in_brief(db_session, raw_root, tmp_path):
    _ready_source(
        db_session,
        raw_root,
        tmp_path,
        display_name="bench-r1-this-is-a-real-user-title",
        scope=USER_SCOPE,
        text="user bench titled source fact",
    )
    titles = _brief_titles(db_session, raw_root, tmp_path)
    assert "bench-r1-this-is-a-real-user-title" in titles


def test_user_e2e_title_visible_in_brief(db_session, raw_root, tmp_path):
    _ready_source(
        db_session,
        raw_root,
        tmp_path,
        display_name="e2e-visible-marker",
        scope=USER_SCOPE,
        text="e2e titled user source fact",
    )
    titles = _brief_titles(db_session, raw_root, tmp_path)
    assert "e2e-visible-marker" in titles


def test_automation_test_excluded_from_user_ask_search(db_session, raw_root, tmp_path):
    auto = _ready_source(
        db_session,
        raw_root,
        tmp_path,
        display_name="normal automation title",
        scope=AUTOMATION_TEST_SCOPE,
        text="automation ask retrieval isolation",
    )
    user = _ready_source(
        db_session,
        raw_root,
        tmp_path,
        display_name="user ask visible",
        scope=USER_SCOPE,
        text="user ask retrieval visible",
    )
    search = SearchService(db_session, _settings(embedding_enable_fake=True))
    hits = search.search("retrieval", {"scope": "all"}, mode="keyword")["results"]
    ids = {item["source_id"] for item in hits}
    assert user.id in ids
    assert auto.id not in ids
