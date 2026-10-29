import json
import re
import uuid

from sqlalchemy import select, text

from app.models.extraction import ContentChunk, ExtractedDocument
from app.models.retrieval import AskCitation, EmbeddingProfile
from app.services.ingestion.service import IngestionService
from app.services.llm.provider import FakeLLMProvider
from app.services.retrieval.ask import AskService
from app.services.retrieval.coverage import (
    allocate_coverage,
    apply_coverage_contract,
    coverage_slots,
    overclaims_unretrieved,
    parse_plan,
    representative_utility,
    select_fallback_candidates,
)
from app.services.retrieval.embedding import _vector
from app.services.retrieval.search import SearchService
from tests.test_retrieval import _extract, _settings


def test_plan_parser_rejects_answers_and_accepts_strategy():
    assert parse_plan('{"summary": "结构化摘要", "facts": []}') is None
    plan = parse_plan(
        '{"mode": "COVERAGE", "needs_cross_source": true, "requested_scope": "CURRENT_FILTER_SCOPE", "reason": "enumerate"}'
    )
    assert plan is not None
    assert plan["mode"] == "COVERAGE"
    assert plan["needs_cross_source"] is True


def test_allocate_coverage_keeps_every_source_and_caps_one_source():
    groups = [
        [{"source_id": "a", "score": 0.9} for _ in range(8)],
        [{"source_id": "b", "score": 0.2}],
        [{"source_id": "c", "score": 0.1}],
    ]
    chosen = allocate_coverage(groups, slots=8, minimum=1, maximum=4)
    counts: dict[str, int] = {}
    for item in chosen:
        counts[item["source_id"]] = counts.get(item["source_id"], 0) + 1
    assert set(counts) == {"a", "b", "c"}
    assert counts["a"] <= 4
    assert coverage_slots(12, slot_budget=8, per_source_cap=4) == 12


def test_fallback_prefers_a_unique_body_over_shared_chrome():
    chrome = "see what is happening and join the conversation"
    assert representative_utility(0.54, 800) > representative_utility(0.50, len(chrome))
    groups = [
        [
            {"chunk_id": "chrome-a", "text_key": chrome, "score": 0.9, "retrieval_reason": "COVERAGE_FALLBACK"},
            {"chunk_id": "body-a", "text_key": "videolingo subtitle body", "score": 0.4, "retrieval_reason": "COVERAGE_FALLBACK"},
        ],
        [
            {"chunk_id": "chrome-b", "text_key": chrome, "score": 0.9, "retrieval_reason": "COVERAGE_FALLBACK"},
            {"chunk_id": "body-b", "text_key": "english speaking prompt body", "score": 0.4, "retrieval_reason": "COVERAGE_FALLBACK"},
        ],
    ]
    chosen = select_fallback_candidates(groups, maximum=2)
    keys = {item["text_key"] for group in chosen for item in group}
    assert chrome not in keys
    assert "videolingo subtitle body" in keys
    assert "english speaking prompt body" in keys


def test_answer_contract_blocks_generalizing_one_source_to_three():
    assert overclaims_unretrieved("这三条资料都可以归入机器学习", 3, 1)
    assert not overclaims_unretrieved("这三条资料分别讲了不同主题", 3, 3)
    answer, code = apply_coverage_contract(
        "这三条资料都可以归入机器学习",
        mode="COVERAGE",
        eligible=3,
        retrieved=1,
        limit=10,
        limited=False,
        missing_titles=["未提取的笔记"],
    )
    assert code == "COVERAGE_SCOPE"
    assert "机器学习" not in answer
    assert "无法判断另外 2 条" in answer
    assert "未提取的笔记" in answer


def _plan(mode: str, cross: bool = False) -> dict:
    return {"mode": mode, "needs_cross_source": cross, "requested_scope": "CURRENT_FILTER_SCOPE", "reason": "test"}


def _install(plan: dict | None, answer):
    original = FakeLLMProvider.complete

    def complete(self, request):
        from app.services.llm.types import LLMResponse

        self.calls.append(request)
        if (request.metadata or {}).get("purpose") == "ask_plan":
            text = json.dumps(plan) if plan else '{"summary": "not a plan"}'
        else:
            text = answer(request.user_content) if callable(answer) else answer
        return LLMResponse(text, None, "fake-model", "FAKE", 11, 7, 18, 4, "stop", {})

    FakeLLMProvider.complete = complete
    return original


def _cite_each_source(user_content: str) -> str:
    citations = []
    parts = []
    for block in re.split(r"(?=^SOURCE )", user_content, flags=re.M):
        match = re.search(r"\[CHUNK: ([0-9a-fA-F-]{36})\][^\n]*\n(.+)", block)
        if match is None:
            continue
        quote = match.group(2).strip()[:180]
        citations.append({"chunk_id": match.group(1), "quote": quote})
        parts.append(f"{quote} [{len(citations)}]")
    return json.dumps({"answer": "根据已检索资料：" + " ".join(parts), "citations": citations}, ensure_ascii=False)


def _filters(*sources) -> dict:
    return {"scope": "mine", "source_ids": [str(source.id) for source in sources]}


def _retrieval(turn) -> dict:
    return (turn.filters_json or {})["retrieval"]


def _citation_sources(db_session, turn) -> set[str]:
    rows = list(db_session.scalars(select(AskCitation).where(AskCitation.ask_turn_id == turn.id)))
    return {str(row.source_item_id) for row in rows}


def test_focused_query_stays_on_the_matching_source(db_session, raw_root, tmp_path):
    english = _extract(db_session, raw_root, tmp_path, "Daily speaking drill for live conversation.")
    video = _extract(db_session, raw_root, tmp_path, "VideoLingo subtitle steps are extract, translate, and dub.")
    learning = _extract(db_session, raw_root, tmp_path, "A notebook widget draws a loss curve.")
    original = _install(_plan("FOCUSED"), _cite_each_source)
    try:
        ask = AskService(db_session, _settings(), inline=True)
        session = ask.create_session("focused")
        turn = ask.start_turn(session.id, "VideoLingo subtitle steps", _filters(english, video, learning))
    finally:
        FakeLLMProvider.complete = original
    meta = _retrieval(turn)
    assert turn.status == "SUCCEEDED"
    assert meta["retrieval_mode"] == "FOCUSED"
    assert meta["coverage_fallback_used"] is False
    assert _citation_sources(db_session, turn) == {str(video.id)}


def test_coverage_reaches_every_source_in_scope(db_session, raw_root, tmp_path):
    english = _extract(db_session, raw_root, tmp_path, "Daily speaking drill for live conversation.")
    video = _extract(db_session, raw_root, tmp_path, "VideoLingo subtitle steps are extract, translate, and dub.")
    learning = _extract(db_session, raw_root, tmp_path, "A notebook widget draws a loss curve.")
    original = _install(_plan("COVERAGE", True), _cite_each_source)
    try:
        ask = AskService(db_session, _settings(), inline=True)
        session = ask.create_session("coverage")
        turn = ask.start_turn(session.id, "请分别概括每条资料", _filters(english, video, learning))
    finally:
        FakeLLMProvider.complete = original
    meta = _retrieval(turn)
    assert turn.status == "SUCCEEDED"
    assert meta["retrieval_mode"] == "COVERAGE"
    assert meta["eligible_source_count"] == 3
    assert meta["retrieved_source_count"] == 3
    assert meta["coverage_complete"] is True
    assert _citation_sources(db_session, turn) == {str(english.id), str(video.id), str(learning.id)}


def test_coverage_prompt_names_the_scope(db_session, raw_root, tmp_path):
    source = _extract(db_session, raw_root, tmp_path, "Daily speaking drill for live conversation.")
    seen: list = []
    original = FakeLLMProvider.complete

    def complete(self, request):
        from app.services.llm.types import LLMResponse

        seen.append(request)
        self.calls.append(request)
        if (request.metadata or {}).get("purpose") == "ask_plan":
            text = json.dumps(_plan("COVERAGE", True))
        else:
            text = _cite_each_source(request.user_content)
        return LLMResponse(text, None, "fake-model", "FAKE", 1, 1, 2, 1, "stop", {})

    FakeLLMProvider.complete = complete
    try:
        ask = AskService(db_session, _settings(), inline=True)
        session = ask.create_session("prompt")
        ask.start_turn(session.id, "请分别概括每条资料", _filters(source))
    finally:
        FakeLLMProvider.complete = original
    answer = next(request for request in seen if request.metadata.get("purpose") == "ask_answer")
    assert "may not generalize" in answer.user_content
    assert "Retrieval mode: COVERAGE" in answer.user_content
    assert f"SOURCE {source.id}" in answer.user_content


def test_missing_source_is_partial_and_not_described_as_complete(db_session, raw_root, tmp_path):
    first = _extract(db_session, raw_root, tmp_path, "Daily speaking drill for live conversation.")
    second = _extract(db_session, raw_root, tmp_path, "VideoLingo subtitle steps are extract, translate, and dub.")
    empty = IngestionService(db_session, raw_root, max_upload_size_bytes=200_000).ingest_text("empty coverage note without extraction").source_item
    original = _install(_plan("COVERAGE", True), _cite_each_source)
    try:
        ask = AskService(db_session, _settings(), inline=True)
        session = ask.create_session("partial")
        turn = ask.start_turn(session.id, "请分别概括每条资料", _filters(first, second, empty))
    finally:
        FakeLLMProvider.complete = original
    meta = _retrieval(turn)
    assert meta["eligible_source_count"] == 3
    assert meta["retrieved_source_count"] == 2
    assert str(empty.id) in meta["missing_source_ids"]
    assert meta["coverage_complete"] is False
    assert turn.status == "PARTIAL"
    assert turn.error_code == "PARTIAL_COVERAGE"
    assert "无法判断另外 1 条" in (turn.answer_markdown or "")


def test_one_source_cannot_be_described_as_all_three(db_session, raw_root, tmp_path):
    only = _extract(db_session, raw_root, tmp_path, "A notebook widget draws a loss curve.")
    missing_a = IngestionService(db_session, raw_root, max_upload_size_bytes=200_000).ingest_text("english note without body").source_item
    missing_b = IngestionService(db_session, raw_root, max_upload_size_bytes=200_000).ingest_text("video note without body").source_item

    def bad_answer(user_content: str) -> str:
        match = re.search(r"\[CHUNK: ([0-9a-fA-F-]{36})\][^\n]*\n(.+)", user_content)
        assert match is not None
        quote = match.group(2).strip()[:180]
        return json.dumps(
            {"answer": "这三条资料都可以归入机器学习", "citations": [{"chunk_id": match.group(1), "quote": quote}]},
            ensure_ascii=False,
        )

    original = _install(_plan("COVERAGE", True), bad_answer)
    try:
        ask = AskService(db_session, _settings(), inline=True)
        session = ask.create_session("guard")
        turn = ask.start_turn(session.id, "这些资料分别属于哪些方向", _filters(only, missing_a, missing_b))
    finally:
        FakeLLMProvider.complete = original
    assert turn.status == "PARTIAL"
    assert turn.error_code == "COVERAGE_SCOPE"
    assert "机器学习" not in (turn.answer_markdown or "")
    assert "无法判断另外 2 条" in (turn.answer_markdown or "")
    assert _citation_sources(db_session, turn) == {str(only.id)}


def test_empty_scope_is_no_evidence(db_session):
    original = _install(_plan("COVERAGE", True), _cite_each_source)
    try:
        ask = AskService(db_session, _settings(), inline=True)
        session = ask.create_session("empty")
        turn = ask.start_turn(session.id, "请分别概括每条资料", {"scope": "mine", "source_ids": [str(uuid.uuid4())]})
    finally:
        FakeLLMProvider.complete = original
    assert turn.status == "NO_EVIDENCE"
    assert _retrieval(turn)["eligible_source_count"] == 0


def test_coverage_is_bounded_when_scope_exceeds_the_limit(db_session, raw_root, tmp_path):
    sources = [
        _extract(db_session, raw_root, tmp_path, f"coverage bound note {index} keeps its own sentence")
        for index in range(3)
    ]
    original = _install(_plan("COVERAGE", True), _cite_each_source)
    try:
        ask = AskService(db_session, _settings(ask_max_coverage_sources=2), inline=True)
        session = ask.create_session("bounded")
        turn = ask.start_turn(session.id, "请分别概括每条资料", _filters(*sources))
    finally:
        FakeLLMProvider.complete = original
    meta = _retrieval(turn)
    assert meta["eligible_source_count"] == 3
    assert meta["retrieved_source_count"] == 2
    assert meta["coverage_limit"] == 2
    assert meta["coverage_limited"] is True
    assert meta["coverage_complete"] is False
    assert turn.status == "PARTIAL"
    assert "不能代表其余资料" in (turn.answer_markdown or "")


def _store_orthogonal_embedding(db_session, source) -> None:
    profile = db_session.scalar(select(EmbeddingProfile).where(EmbeddingProfile.is_active.is_(True)))
    assert profile is not None
    chunk = db_session.scalar(
        select(ContentChunk)
        .join(ExtractedDocument, ExtractedDocument.id == ContentChunk.extracted_document_id)
        .where(ExtractedDocument.source_item_id == source.id)
    )
    assert chunk is not None
    vector = _vector(chunk.content, 1024)
    db_session.execute(
        text(
            """
            INSERT INTO chunk_embeddings (
                id, content_chunk_id, embedding_profile_id, provider_type, model_name,
                dimensions, embedding, content_hash, created_at
            ) VALUES (
                :id, :chunk_id, :profile, 'FAKE', 'fake-embedding',
                1024, CAST(:embedding AS vector), :digest, NOW()
            )
            """
        ),
        {
            "id": uuid.uuid4(),
            "chunk_id": chunk.id,
            "profile": profile.id,
            "embedding": str(vector),
            "digest": uuid.uuid4().hex,
        },
    )
    db_session.flush()


def test_coverage_fallback_keeps_a_source_below_the_distance_threshold(db_session, raw_root, tmp_path):
    source = _extract(db_session, raw_root, tmp_path, "sandbox isolation keeps workloads apart")
    _store_orthogonal_embedding(db_session, source)
    question = "请用机器人视角分别概括每条资料"
    settings = _settings()
    missed = SearchService(db_session, settings).search(question, _filters(source), mode="hybrid")
    assert source.id not in {item["source_id"] for item in missed["results"]}
    original = _install(_plan("COVERAGE", True), _cite_each_source)
    try:
        ask = AskService(db_session, settings, inline=True)
        session = ask.create_session("fallback")
        turn = ask.start_turn(session.id, question, _filters(source))
    finally:
        FakeLLMProvider.complete = original
    meta = _retrieval(turn)
    assert turn.status == "SUCCEEDED"
    assert meta["coverage_fallback_used"] is True
    assert meta["retrieval_reasons"][str(source.id)] == "COVERAGE_FALLBACK"
    assert _citation_sources(db_session, turn) == {str(source.id)}


def test_focused_irrelevant_query_does_not_use_coverage_fallback(db_session, raw_root, tmp_path):
    source = _extract(db_session, raw_root, tmp_path, "sandbox isolation keeps workloads apart")
    _store_orthogonal_embedding(db_session, source)
    original = _install(_plan("FOCUSED"), _cite_each_source)
    try:
        ask = AskService(db_session, _settings(), inline=True)
        session = ask.create_session("irrelevant")
        turn = ask.start_turn(session.id, "机器人完全无关的问题", _filters(source))
    finally:
        FakeLLMProvider.complete = original
    meta = _retrieval(turn)
    assert turn.status == "NO_EVIDENCE"
    assert meta["retrieval_mode"] == "FOCUSED"
    assert meta["coverage_fallback_used"] is False
