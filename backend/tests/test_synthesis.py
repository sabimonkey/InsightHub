import json
import uuid
from datetime import datetime, timezone

import fitz
from docx import Document
from io import BytesIO
from sqlalchemy import func, select

from app.core.config import Settings
from app.models.analysis import AnalysisResult, AnalysisRun, Claim, Evidence
from app.models.discovery import OriginalSourceCandidate, SourceDiscoveryRun, SourceRelation
from app.models.extraction import ContentChunk
from app.models.ingestion_record import IngestionRecord
from app.models.organization import Category, SourceCategoryAssignment, SourceTopicAssignment, Topic
from app.models.source_asset import SourceAsset
from app.models.source_item import SourceItem
from app.models.synthesis import Brief, BriefCitation, BriefSource
from app.services.extraction.service import ExtractionService
from app.services.ingestion.service import IngestionService
from app.services.llm.provider import FakeLLMProvider
from app.services.synthesis.exporting import write_docx, write_markdown, write_pdf
from app.services.synthesis.service import SynthesisService


def _settings(**kwargs) -> Settings:
    values = dict(llm_enable_fake=True, llm_default_provider="FAKE", brief_inline=True, synthesis_batch_size=4, analysis_max_output_tokens=400)
    values.update(kwargs)
    return Settings(**values)


def _source(db_session, raw_root, tmp_path, text: str, slug: str):
    created = IngestionService(db_session, raw_root, max_upload_size_bytes=200_000).ingest_text(text)
    ExtractionService(
        db_session, raw_root, tmp_path / "extracted", inline=True, chunk_max_chars=400, chunk_overlap_chars=0,
        max_pdf_pages=1, web_timeout=1, web_max_bytes=1000, web_max_redirects=1,
    ).schedule(created.source_item.id, "MANUAL", force=True)
    source = created.source_item
    chunk = db_session.scalar(select(ContentChunk).join(ContentChunk.document).where(ContentChunk.document.has(source_item_id=source.id)))
    run = AnalysisRun(
        id=uuid.uuid4(), source_item_id=source.id, extracted_document_id=chunk.extracted_document_id, provider_type="FAKE",
        model_name="fake-model", prompt_name="source_analysis", prompt_version="1.0.0", status="SUCCEEDED", is_current=True,
        metadata_json={}, created_at=datetime.now(timezone.utc),
    )
    db_session.add(run)
    db_session.flush()
    result = AnalysisResult(id=uuid.uuid4(), analysis_run_id=run.id, summary="结构化摘要", raw_structured_json={}, created_at=datetime.now(timezone.utc))
    db_session.add(result)
    db_session.flush()
    claim = Claim(id=uuid.uuid4(), analysis_result_id=result.id, claim_type="FACT", text=chunk.content[:80], confidence=0.9, importance=3, sequence=1, created_at=datetime.now(timezone.utc))
    db_session.add(claim)
    db_session.flush()
    db_session.add(Evidence(id=uuid.uuid4(), claim_id=claim.id, content_chunk_id=chunk.id, quote_text=chunk.content[:80], created_at=datetime.now(timezone.utc)))
    category = db_session.scalar(select(Category).where(Category.slug == slug))
    db_session.add(SourceCategoryAssignment(id=uuid.uuid4(), source_item_id=source.id, category_id=category.id, origin="USER", status="ACTIVE", is_primary=True, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)))
    db_session.commit()
    return source, chunk, claim


def _filters(slug: str, **extra):
    today = datetime.now(timezone.utc).date().isoformat()
    body = {"start_date": today, "end_date": today, "date_basis": "COLLECTED_AT", "detail_level": "STANDARD", "category_slugs": [slug]}
    body.update(extra)
    return body


def _private_category_slug(db_session) -> str:
    slug = f"synthesis-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    db_session.add(
        Category(
            id=uuid.uuid4(),
            name=slug,
            slug=slug,
            display_order=99,
            is_system_default=False,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
    )
    db_session.flush()
    return slug


def test_brief_generation_does_not_require_embedding(db_session, raw_root, tmp_path, monkeypatch):
    from app.services.retrieval.embedding import EmbeddingError

    def down(self, texts):
        raise EmbeddingError("PROVIDER_UNAVAILABLE", "ConnectError")

    monkeypatch.setattr("app.services.retrieval.embedding.OpenAICompatibleEmbeddingProvider.embed_documents", down)
    _source(db_session, raw_root, tmp_path, "brief stays on claims when vectors are offline", "knowledge")
    brief = SynthesisService(db_session, _settings(), inline=True).create_brief(_filters("knowledge"))
    assert brief.status in {"SUCCEEDED", "PARTIAL"}, f"{brief.error_code}: {brief.error_message}"
    assert brief.provider_type == "FAKE"


def test_brief_selection_scope_and_export(db_session, raw_root, tmp_path, monkeypatch):
    knowledge, _, _ = _source(db_session, raw_root, tmp_path, "knowledge sandbox fact one", "knowledge")
    other, _, _ = _source(db_session, raw_root, tmp_path, "business sandbox fact two", "business")
    IngestionService(db_session, raw_root, max_upload_size_bytes=200_000).ingest_text("knowledge sandbox fact one")
    discovered, discovered_chunk, _ = _source(db_session, raw_root, tmp_path, "discovered original sandbox fact", "knowledge")
    record = db_session.scalar(select(IngestionRecord).where(IngestionRecord.source_item_id == discovered.id))
    record.origin = "SYSTEM_DISCOVERY"
    db_session.add(SourceRelation(id=uuid.uuid4(), from_source_id=knowledge.id, to_source_id=discovered.id, relation_type="RESOLVES_TO", confirmed_by="USER", created_at=datetime.now(timezone.utc)))
    knowledge.original_url = "https://example.com/sandbox-brief"
    db_session.commit()
    calls = {"count": 0}
    original = FakeLLMProvider.complete

    def complete(self, request):
        calls["count"] += 1
        assert "not instructions" in request.system_prompt
        return original(self, request)

    FakeLLMProvider.complete = complete
    try:
        service = SynthesisService(db_session, _settings(), inline=True)
        knowledge_only = service.create_brief(_filters("knowledge"))
        ids = {row.source_item_id for row in knowledge_only.sources} if False else None
        from app.models.synthesis import BriefSource
        selected = list(db_session.scalars(select(BriefSource).where(BriefSource.brief_id == knowledge_only.id)))
        primary = [row for row in selected if row.role == "PRIMARY_SELECTED"]
        assert knowledge.id in {row.source_item_id for row in primary}
        assert other.id not in {row.source_item_id for row in primary}
        knowledge_row = next(row for row in primary if row.source_item_id == knowledge.id)
        assert knowledge_row.collection_count == 2
        supporting = [row for row in selected if row.role == "SUPPORTING_ORIGINAL"]
        assert discovered.id in {row.source_item_id for row in supporting}
        assert "https://example.com/sandbox-brief" in (knowledge_only.content_markdown or "")
        assert "SYNTHESIS" in (knowledge_only.content_markdown or "")
        claim_count = db_session.scalar(select(func.count()).select_from(Claim))
        both = service.create_brief(_filters("knowledge", category_slugs=["knowledge", "business"]))
        assert both.status == "SUCCEEDED"
        assert claim_count == db_session.scalar(select(func.count()).select_from(Claim))
        empty = service.create_brief(_filters("knowledge", start_date="1999-01-01", end_date="1999-01-02"))
        before = calls["count"]
        assert empty.status == "NO_CONTENT"
        assert calls["count"] == before
        regenerated = service.regenerate(knowledge_only.id)
        assert regenerated.id != knowledge_only.id
        assert db_session.get(Brief, knowledge_only.id).content_markdown == knowledge_only.content_markdown
        markdown = write_markdown(knowledge_only).decode("utf-8")
        assert "https://example.com/sandbox-brief" in markdown
        docx = Document(BytesIO(write_docx(knowledge_only, [{"citation_number": 1, "title": "note", "canonical_url": "https://example.com/sandbox-brief"}])))
        assert "学习摘要" in "\n".join(paragraph.text for paragraph in docx.paragraphs)
        assert any("hyperlink" in relationship.reltype for relationship in docx.part.rels.values())
        pdf = fitz.open(stream=write_pdf(knowledge_only), filetype="pdf")
        assert pdf.page_count > 0
        assert "学习摘要" in "".join(page.get_text() for page in pdf)
        pdf.close()
        assert discovered_chunk.id
    finally:
        FakeLLMProvider.complete = original


def test_topic_partial_privacy_and_invalid_citation(db_session, raw_root, tmp_path, monkeypatch):
    source, chunk, claim = _source(db_session, raw_root, tmp_path, "agent topic sandbox agreement", "knowledge")
    second, second_chunk, second_claim = _source(db_session, raw_root, tmp_path, "agent topic sandbox disagreement", "knowledge")
    second_claim.claim_type = "SOURCE_CLAIM"
    topic = Topic(id=uuid.uuid4(), name="Agent", normalized_name=f"agent-{uuid.uuid4().hex[:8]}", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    db_session.add(topic)
    db_session.flush()
    for item in (source, second):
        db_session.add(SourceTopicAssignment(id=uuid.uuid4(), source_item_id=item.id, topic_id=topic.id, origin="USER", status="ACTIVE", created_at=datetime.now(timezone.utc)))
    unanalyzed = IngestionService(db_session, raw_root, max_upload_size_bytes=200_000).ingest_text("knowledge collected but not analyzed")
    ExtractionService(
        db_session, raw_root, tmp_path / "extracted", inline=True, chunk_max_chars=200, chunk_overlap_chars=0,
        max_pdf_pages=1, web_timeout=1, web_max_bytes=1000, web_max_redirects=1,
    ).schedule(unanalyzed.source_item.id, "MANUAL", force=True)
    category = db_session.scalar(select(Category).where(Category.slug == "knowledge"))
    db_session.add(SourceCategoryAssignment(id=uuid.uuid4(), source_item_id=unanalyzed.source_item.id, category_id=category.id, origin="USER", status="ACTIVE", is_primary=True, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)))
    topic_count = db_session.scalar(select(func.count()).select_from(Topic))
    db_session.commit()
    service = SynthesisService(db_session, _settings(synthesis_batch_size=1), inline=True)
    synthesis = service.create_topic_synthesis(topic.id)
    assert synthesis.status == "SUCCEEDED"
    assert "DISAGREEMENT" in (synthesis.content_markdown or "") or "SOURCE_VIEW" in (synthesis.content_markdown or "")
    assert chunk.id and second_chunk.id
    assert db_session.scalar(select(func.count()).select_from(Topic)) == topic_count
    partial = service.create_brief(_filters("knowledge"))
    assert partial.excluded_source_count >= 1
    assert partial.exclusion_reasons_json.get("NO_ANALYSIS", 0) >= 1
    source.privacy_level = "SENSITIVE"
    db_session.commit()
    monkeypatch.setenv("GENERIC_LLM_API_KEY", "not-a-real-key")
    from app.services.llm.routing import update_routes

    blocked_settings = _settings(llm_enable_fake=False, llm_default_provider="GENERIC_OPENAI_COMPATIBLE", generic_llm_base_url="https://example.invalid/v1", generic_llm_model="m")
    update_routes(
        db_session,
        blocked_settings,
        {name: "GENERIC_OPENAI_COMPATIBLE" for name in ("EXTRACTION_AI", "ANALYSIS", "ASK_PLANNER", "ASK_ANSWER", "BRIEF")},
    )
    blocked = SynthesisService(
        db_session,
        _settings(llm_enable_fake=False, llm_default_provider="GENERIC_OPENAI_COMPATIBLE", generic_llm_base_url="https://example.invalid/v1", generic_llm_model="m"),
        inline=True,
    ).create_brief(_filters("knowledge"))
    assert blocked.error_code == "BRIEF_PRIVACY_PROVIDER_NOT_ALLOWED"
    original = FakeLLMProvider.complete

    def bad(self, request):
        from app.services.llm.types import LLMResponse
        return LLMResponse('{"title":"x","executive_summary":"x","themes":[{"title":"t","summary":"s","points":[{"text":"bad","statement_type":"FACT","citations":[{"source_id":"%s","claim_id":"%s","chunk_id":"%s","quote":"missing"}]}]}]}' % (source.id, claim.id, uuid.uuid4()), None, "fake", "FAKE", 1, 1, 2, 1, "stop", {})

    FakeLLMProvider.complete = bad
    try:
        failed = SynthesisService(db_session, _settings(), inline=True).create_brief(_filters("knowledge"))
        assert failed.status == "FAILED"
    finally:
        FakeLLMProvider.complete = original


def _candidate(db_session, source_id, published_at):
    run = SourceDiscoveryRun(
        id=uuid.uuid4(), source_item_id=source_id, status="SUCCEEDED", resolver_type="test", resolver_version="1",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(run)
    db_session.flush()
    db_session.add(
        OriginalSourceCandidate(
            id=uuid.uuid4(), discovery_run_id=run.id, source_item_id=source_id, candidate_url="https://example.com/published",
            normalized_candidate_url="https://example.com/published", candidate_type="ARTICLE", score=1, confidence=1,
            match_reasons_json=[], evidence_json={}, rank=1, status="CONFIRMED", published_at=published_at,
            created_at=datetime.now(timezone.utc),
        )
    )


def test_published_at_topic_filter_private_cloud_and_filename(db_session, raw_root, tmp_path, monkeypatch):
    published, _, _ = _source(db_session, raw_root, tmp_path, "published today sandbox fact", "knowledge")
    older, _, _ = _source(db_session, raw_root, tmp_path, "published earlier sandbox fact", "knowledge")
    topical, _, _ = _source(db_session, raw_root, tmp_path, "agent topic filter sandbox fact", "knowledge")
    other_topic, _, _ = _source(db_session, raw_root, tmp_path, "other topic sandbox fact", "knowledge")
    uploaded, _, _ = _source(db_session, raw_root, tmp_path, "uploaded file sandbox fact", "knowledge")
    now = datetime.now(timezone.utc)
    _candidate(db_session, published.id, now)
    _candidate(db_session, older.id, datetime(1999, 1, 1, tzinfo=timezone.utc))
    topic = Topic(id=uuid.uuid4(), name="Agent Filter", normalized_name=f"agent-filter-{uuid.uuid4().hex[:8]}", created_at=now, updated_at=now)
    db_session.add(topic)
    db_session.flush()
    db_session.add(SourceTopicAssignment(id=uuid.uuid4(), source_item_id=topical.id, topic_id=topic.id, origin="USER", status="ACTIVE", created_at=now))
    uploaded.original_url = None
    uploaded.canonical_url = None
    db_session.add(
        SourceAsset(
            id=uuid.uuid4(), source_item_id=uploaded.id, original_filename="notes.pdf", stored_path="data/raw/aa/bb/notes.pdf",
            mime_type="application/pdf", size_bytes=12, sha256=uuid.uuid4().hex + uuid.uuid4().hex[:32], created_at=now,
        )
    )
    db_session.commit()
    service = SynthesisService(db_session, _settings(), inline=True)
    today = now.date().isoformat()
    by_published = service.create_brief(_filters("knowledge", date_basis="PUBLISHED_AT", start_date=today, end_date=today))
    published_rows = list(db_session.scalars(select(BriefSource).where(BriefSource.brief_id == by_published.id)))
    primary_ids = {row.source_item_id for row in published_rows if row.role == "PRIMARY_SELECTED"}
    assert published.id in primary_ids
    assert older.id not in primary_ids
    by_topic = service.create_brief(_filters("knowledge", topic_ids=[str(topic.id)]))
    topic_rows = list(db_session.scalars(select(BriefSource).where(BriefSource.brief_id == by_topic.id)))
    topic_ids = {row.source_item_id for row in topic_rows if row.role == "PRIMARY_SELECTED"}
    assert topical.id in topic_ids
    assert other_topic.id not in topic_ids
    uploaded_brief = service.create_brief(_filters("knowledge"))
    assert "用户上传：notes.pdf" in (uploaded_brief.content_markdown or "")
    published.privacy_level = "PRIVATE"
    db_session.commit()
    monkeypatch.setenv("GENERIC_LLM_API_KEY", "not-a-real-key")
    monkeypatch.setattr(
        "app.services.synthesis.service.build_provider",
        lambda spec, settings, client=None, fake=None, session=None: FakeLLMProvider(),
    )
    from app.services.llm.routing import update_routes

    allowed_settings = _settings(llm_enable_fake=False, llm_default_provider="GENERIC_OPENAI_COMPATIBLE", generic_llm_base_url="https://example.invalid/v1", generic_llm_model="m")
    update_routes(
        db_session,
        allowed_settings,
        {name: "GENERIC_OPENAI_COMPATIBLE" for name in ("EXTRACTION_AI", "ANALYSIS", "ASK_PLANNER", "ASK_ANSWER", "BRIEF")},
    )
    allowed = SynthesisService(
        db_session,
        _settings(llm_enable_fake=False, llm_default_provider="GENERIC_OPENAI_COMPATIBLE", generic_llm_base_url="https://example.invalid/v1", generic_llm_model="m"),
        inline=True,
    ).create_brief(_filters("knowledge", start_date=today, end_date=today, date_basis="PUBLISHED_AT"))
    assert allowed.error_code != "BRIEF_PRIVACY_PROVIDER_NOT_ALLOWED"
    assert allowed.status == "SUCCEEDED"


def test_large_corpus_uses_bounded_hierarchy(db_session, raw_root, tmp_path):
    calls = []
    original = FakeLLMProvider.complete

    def complete(self, request):
        calls.append(request)
        return original(self, request)

    scope = _private_category_slug(db_session)
    created = []
    for index in range(8):
        source, chunk, claim = _source(db_session, raw_root, tmp_path, f"hierarchy source {index} sandbox", scope)
        chunk.content = ("a" * 240) + "LONGQUOTE_MARKER" + ("b" * 2400)
        evidence = db_session.scalar(select(Evidence).where(Evidence.claim_id == claim.id))
        evidence.quote_text = chunk.content
        created.append((source, claim, chunk))
    db_session.commit()
    FakeLLMProvider.complete = complete
    try:
        service = SynthesisService(
            db_session,
            _settings(default_llm_context_window=1400, analysis_max_output_tokens=180, synthesis_batch_size=2),
            inline=True,
        )
        brief = service.create_brief(_filters(scope))
        assert service.reduction_levels >= 2
        assert brief.status in {"SUCCEEDED", "PARTIAL"}
        finals = [request for request in calls if "Stage: final" in request.user_content]
        assert finals
        assert "LONGQUOTE_MARKER" not in finals[-1].user_content
        assert all(service.fits_context(request) for request in calls)
        cited_rows = list(db_session.scalars(select(BriefCitation).where(BriefCitation.brief_id == brief.id)))
        cited = {row.claim_id for row in cited_rows}
        original_claims = {claim.id for _, claim, _ in created}
        assert cited
        assert cited <= original_claims
        assert all(row.content_chunk_id for row in cited_rows)
    finally:
        FakeLLMProvider.complete = original


def test_provider_context_window_keeps_short_claims(db_session, raw_root, tmp_path, monkeypatch):
    source, chunk, claim = _source(db_session, raw_root, tmp_path, "window sandbox seed", "knowledge")
    quotes = [f"BRIEFWINDOW{index:02d} " + ("q" * 74) for index in range(36)]
    chunk.content = "\n".join(quotes)
    claim.text = quotes[0]
    evidence = db_session.scalar(select(Evidence).where(Evidence.claim_id == claim.id))
    evidence.quote_text = quotes[0]
    result_id = claim.analysis_result_id
    for index, quote in enumerate(quotes[1:], start=2):
        extra = Claim(
            id=uuid.uuid4(), analysis_result_id=result_id, claim_type="FACT", text=quote, confidence=0.9,
            importance=2, sequence=index, created_at=datetime.now(timezone.utc),
        )
        db_session.add(extra)
        db_session.flush()
        db_session.add(Evidence(id=uuid.uuid4(), claim_id=extra.id, content_chunk_id=chunk.id, quote_text=quote, created_at=datetime.now(timezone.utc)))
    db_session.commit()
    narrow = SynthesisService(
        db_session,
        _settings(default_llm_context_window=8000, analysis_max_output_tokens=6000),
        inline=True,
    ).create_brief(_filters("knowledge"))
    assert narrow.status == "FAILED"
    assert narrow.error_code == "SYNTHESIS_CONTEXT_LIMIT_EXCEEDED"

    class Wide(FakeLLMProvider):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.context_window = 32768

    monkeypatch.setattr("app.services.synthesis.service.FakeLLMProvider", Wide)
    wide = SynthesisService(
        db_session,
        _settings(default_llm_context_window=8000, analysis_max_output_tokens=6000),
        inline=True,
    )
    brief = wide.create_brief(_filters("knowledge"))
    assert brief.status in {"SUCCEEDED", "PARTIAL"}
    assert wide.reduction_levels == 0
    assert brief.id != narrow.id


def test_brief_request_uses_synthesis_schema(db_session, raw_root, tmp_path):
    _source(db_session, raw_root, tmp_path, "schema sandbox fact", "knowledge")
    seen = {}
    original = FakeLLMProvider.complete

    def complete(self, request):
        if "Stage: final" in request.user_content:
            seen["schema"] = request.response_schema
            seen["name"] = (request.metadata or {}).get("schema_name")
            seen["schema_in_prompt"] = "executive_summary" in request.user_content and "key_facts" in request.user_content and "chunk_id" in request.user_content
        return original(self, request)

    FakeLLMProvider.complete = complete
    try:
        brief = SynthesisService(db_session, _settings(), inline=True).create_brief(_filters("knowledge"))
    finally:
        FakeLLMProvider.complete = original
    assert brief.status in {"SUCCEEDED", "PARTIAL"}
    assert seen["name"] == "brief_synthesis"
    assert seen["schema"]["required"] == ["title", "executive_summary", *["themes", "key_facts", "agreements", "disagreements", "new_developments", "knowledge_to_remember", "open_questions", "projects_or_tools"]]
    assert seen["schema"]["properties"]["themes"]["items"]["properties"]["points"]["items"]["properties"]["citations"]["items"]["required"] == ["source_id", "claim_id", "chunk_id", "quote"]
    assert seen["schema_in_prompt"] is True


def test_citation_quote_and_uncited_source(db_session, raw_root, tmp_path):
    scope = _private_category_slug(db_session)
    kept, chunk, claim = _source(db_session, raw_root, tmp_path, "kept sandbox fact alpha", scope)
    dropped_source, _, _ = _source(db_session, raw_root, tmp_path, "dropped sandbox fact beta", scope)
    chunk.content = (chunk.content or "") + "\nFOREIGN_CHUNK_SPAN"
    result_id = claim.analysis_result_id
    opinion = Claim(
        id=uuid.uuid4(), analysis_result_id=result_id, claim_type="SOURCE_CLAIM", text="作者认为这只是个人看法",
        confidence=0.8, importance=2, sequence=2, created_at=datetime.now(timezone.utc),
    )
    db_session.add(opinion)
    db_session.flush()
    db_session.add(Evidence(id=uuid.uuid4(), claim_id=opinion.id, content_chunk_id=chunk.id, quote_text="FOREIGN_CHUNK_SPAN", created_at=datetime.now(timezone.utc)))
    db_session.commit()
    service = SynthesisService(db_session, _settings(), inline=True)
    assert service._check_citation(
        {"source_id": str(kept.id), "claim_id": str(claim.id), "chunk_id": str(chunk.id), "quote": "FOREIGN_CHUNK_SPAN"},
        {kept.id},
    ) is None
    evidence = db_session.scalar(select(Evidence).where(Evidence.claim_id == claim.id))
    assert service._check_citation(
        {"source_id": str(kept.id), "claim_id": str(claim.id), "chunk_id": str(chunk.id), "quote": evidence.quote_text},
        {kept.id},
    ) is not None
    original = FakeLLMProvider.complete

    def complete(self, request):
        response = original(self, request)
        if "Evidence packets:" not in request.user_content:
            return response
        payload = json.loads(response.text)

        def keep(points):
            kept_points = []
            for point in points:
                citations = [item for item in point.get("citations") or [] if item.get("source_id") == str(kept.id)]
                if not citations:
                    continue
                if any(item.get("claim_id") == str(opinion.id) for item in citations):
                    point = {**point, "statement_type": "FACT"}
                kept_points.append({**point, "citations": citations})
            return kept_points

        for theme in payload.get("themes") or []:
            theme["points"] = keep(theme.get("points") or [])
        for key in ("key_facts", "agreements", "disagreements", "new_developments", "knowledge_to_remember", "open_questions", "projects_or_tools"):
            payload[key] = keep(payload.get(key) or [])
        response.text = json.dumps(payload, ensure_ascii=False)
        return response

    FakeLLMProvider.complete = complete
    try:
        brief = service.create_brief(_filters(scope))
    finally:
        FakeLLMProvider.complete = original
    rows = list(db_session.scalars(select(BriefSource).where(BriefSource.brief_id == brief.id)))
    by_source = {row.source_item_id: row for row in rows}
    assert by_source[kept.id].included is True
    assert by_source[dropped_source.id].included is False
    assert by_source[dropped_source.id].exclusion_reason == "NOT_CITED"
    assert brief.status == "PARTIAL"
    assert brief.exclusion_reasons_json.get("NOT_CITED") == 1
    opinions = [
        point for point in brief.structured_result_json["themes"][0]["points"]
        if any(item["claim_id"] == str(opinion.id) for item in point["citations"])
    ]
    assert opinions
    assert opinions[0]["statement_type"] == "SOURCE_VIEW"


def test_unexpected_generation_error_fails_the_brief(db_session, raw_root, tmp_path):
    _source(db_session, raw_root, tmp_path, "interrupt sandbox fact", "knowledge")
    service = SynthesisService(db_session, _settings(), inline=True)

    def boom(*args, **kwargs):
        raise RuntimeError("worker interrupted")

    service._generate = boom
    brief = service.create_brief(_filters("knowledge"))
    assert brief.status == "FAILED"
    assert brief.error_code == "JOB_FAILED"
    assert brief.completed_at is not None


def test_invalid_json_failure_persists_safe_attempt_diagnostics(db_session, raw_root, tmp_path, monkeypatch):
    from app.services.llm.types import LLMResponse

    _source(db_session, raw_root, tmp_path, "invalid JSON sandbox fact", "knowledge")

    def malformed(self, request):
        return LLMResponse("not JSON", None, "fake-model", "FAKE", 12, 5, 17, 4, "stop", {"strategy": "fake"})

    monkeypatch.setattr(FakeLLMProvider, "complete", malformed)
    brief = SynthesisService(db_session, _settings(), inline=True).create_brief(_filters("knowledge"))

    assert brief.status == "FAILED"
    assert brief.error_code == "STRUCTURED_OUTPUT_INVALID"
    diagnostics = brief.filters_json["generation_diagnostics"]
    assert diagnostics["request_count"] == 2
    assert len(diagnostics["attempts"]) == 2
    assert all(attempt["max_tokens"] > 0 for attempt in diagnostics["attempts"])
    assert "not JSON" not in str(diagnostics)
