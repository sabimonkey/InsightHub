import json
import uuid

import pytest
import redis

from app.core.config import get_settings
from app.models.retrieval import AskCitation, AskTurn
from app.services.llm.provider import FakeLLMProvider, LLMError
from app.services.llm.types import LLMRequest
from app.services.retrieval.ask import AskService
from app.services.retrieval.ask_events import AskTurnEventPublisher, read_stream_entries, stream_key
from app.services.retrieval.ask_partial import partial_answer_text
from app.services.retrieval.indexing import IndexingService
from app.services.retrieval.embedding import FakeEmbeddingProvider
from sqlalchemy import select

from tests.test_retrieval import _extract, _settings


def _redis_available() -> bool:
    settings = get_settings()
    try:
        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=0.5)
        client.ping()
        client.close()
        return True
    except Exception:
        return False


redis_required = pytest.mark.skipif(not _redis_available(), reason="redis unavailable")


def test_partial_answer_text_extracts_growing_json():
    buffer = '{"answer": "hello wor'
    assert partial_answer_text(buffer) == "hello wor"
    buffer = '{"answer": "hello\\nworld'
    assert partial_answer_text(buffer) == "hello\nworld"


@redis_required
def test_fake_stream_publishes_deltas_and_final(db_session, raw_root, tmp_path):
    source = _extract(db_session, raw_root, tmp_path, "streaming sandbox note for ask")
    settings = _settings(vector_max_distance=-0.01, ask_streaming_enabled=True)
    IndexingService(db_session, settings, FakeEmbeddingProvider()).backfill()
    ask = AskService(db_session, settings, inline=True)
    session = ask.create_session("stream")
    turn = ask.start_turn(session.id, "what is in the sandbox note", filters={"source_ids": [str(source.id)]})
    assert turn.status == "SUCCEEDED"
    entries = read_stream_entries(turn.id)
    events = [row[1] for row in entries]
    assert "planning" in events
    assert "retrieving" in events
    assert "delta" in events
    assert "validating" in events
    assert "final" in events
    deltas = [row[2].get("text") for row in entries if row[1] == "delta"]
    assert sum(len(str(item or "")) for item in deltas) > 0
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    ttl = client.ttl(stream_key(turn.id))
    client.close()
    assert ttl > 0


@redis_required
def test_stream_without_subscriber_still_persists(db_session, raw_root, tmp_path):
    source = _extract(db_session, raw_root, tmp_path, "subscriber absent sandbox")
    settings = _settings(vector_max_distance=-0.01, ask_streaming_enabled=True)
    IndexingService(db_session, settings, FakeEmbeddingProvider()).backfill()
    ask = AskService(db_session, settings, inline=True)
    session = ask.create_session("nosub")
    turn = ask.start_turn(session.id, "sandbox absent", filters={"source_ids": [str(source.id)]})
    persisted = db_session.get(AskTurn, turn.id)
    assert persisted is not None
    assert persisted.status == "SUCCEEDED"
    assert persisted.answer_markdown


def test_stream_provider_exception_fails_turn(db_session, raw_root, tmp_path, monkeypatch):
    source = _extract(db_session, raw_root, tmp_path, "stream fail sandbox")
    settings = _settings(vector_max_distance=-0.01, ask_streaming_enabled=True)
    IndexingService(db_session, settings, FakeEmbeddingProvider()).backfill()

    class Broken(FakeLLMProvider):
        def stream_completion(self, request, on_delta=None):
            if (request.metadata or {}).get("purpose") == "ask_answer":
                raise LLMError("PROVIDER_UNAVAILABLE", "stream broke")
            return super().stream_completion(request, on_delta=on_delta)

    monkeypatch.setattr(AskService, "_open_provider", lambda self, spec: Broken())
    ask = AskService(db_session, settings, inline=True)
    session = ask.create_session("fail")
    turn = ask.start_turn(session.id, "sandbox fail", filters={"source_ids": [str(source.id)]})
    assert turn.status == "FAILED"
    assert turn.error_code == "PROVIDER_UNAVAILABLE"


@redis_required
def test_stream_partial_invalid_citation(db_session, raw_root, tmp_path, monkeypatch):
    source = _extract(db_session, raw_root, tmp_path, "partial citation sandbox text")
    settings = _settings(vector_max_distance=-0.01, ask_streaming_enabled=True)
    IndexingService(db_session, settings, FakeEmbeddingProvider()).backfill()

    def bad_answer(_request: LLMRequest) -> str:
        return json.dumps(
            {
                "answer": "draft with bad cite [1]",
                "citations": [{"chunk_id": str(uuid.uuid4()), "quote": "missing"}],
            },
            ensure_ascii=False,
        )

    plan = json.dumps(
        {
            "mode": "FOCUSED",
            "needs_cross_source": False,
            "requested_scope": "CURRENT_FILTER_SCOPE",
            "reason": "test",
        }
    )
    provider = FakeLLMProvider(script=[plan, bad_answer])
    monkeypatch.setattr(AskService, "_open_provider", lambda self, spec: provider)
    ask = AskService(db_session, settings, inline=True)
    session = ask.create_session("partial")
    turn = ask.start_turn(session.id, "sandbox partial", filters={"source_ids": [str(source.id)]})
    assert turn.status == "PARTIAL"
    assert turn.error_code == "NO_VALIDATED_CITATIONS"
    citations = list(db_session.scalars(select(AskCitation).where(AskCitation.ask_turn_id == turn.id)))
    assert not citations


@redis_required
def test_redis_stream_replay_from_cursor(db_session, raw_root, tmp_path):
    source = _extract(db_session, raw_root, tmp_path, "replay sandbox cursor")
    settings = _settings(vector_max_distance=-0.01, ask_streaming_enabled=True)
    IndexingService(db_session, settings, FakeEmbeddingProvider()).backfill()
    ask = AskService(db_session, settings, inline=True)
    session = ask.create_session("replay")
    turn = ask.start_turn(session.id, "sandbox replay", filters={"source_ids": [str(source.id)]})
    all_entries = read_stream_entries(turn.id)
    assert len(all_entries) >= 3
    first_id = all_entries[0][0]
    replay = read_stream_entries(turn.id, last_id=first_id)
    assert replay
    assert replay[0][0] != first_id or len(replay) < len(all_entries)
