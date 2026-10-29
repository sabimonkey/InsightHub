"""Ask planner / answer benchmark with fixed retrieval packets."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT, Settings
from app.models.extraction import ContentChunk, ExtractedDocument
from app.models.source_item import SourceItem
from app.services.llm.registry import build_provider
from app.services.llm.routing import resolve_workflow
from app.services.llm.types import LLMError, LLMRequest
from app.services.analysis.schema import extract_json_object
from app.services.retrieval.ask import AskService
from app.services.retrieval.coverage import ANSWER_SCHEMA, COVERAGE, parse_plan
from app.services.retrieval.embedding import EmbeddingError
from app.services.retrieval.search import SearchService


def run_planner(session: Session, settings: Settings, question: str, provider_type: str) -> dict[str, Any]:
    spec = resolve_workflow(session, settings, "ASK_PLANNER", provider_type)
    provider = build_provider(spec, settings)
    started = time.perf_counter()
    ask = AskService(session, settings, inline=True)
    plan = ask._plan(provider, question)
    latency = int((time.perf_counter() - started) * 1000)
    return {
        "provider": spec.provider_type,
        "model": getattr(provider, "model", spec.model),
        "latency_ms": latency,
        "parse_success": not plan.get("fallback"),
        "mode": plan.get("mode"),
        "planner_latency_ms": plan.get("planner_latency_ms"),
        "input_tokens": plan.get("input_tokens"),
        "output_tokens": plan.get("output_tokens"),
        "reason": plan.get("reason"),
    }


def build_retrieval_packet(session: Session, settings: Settings, question: str, planner_provider: str | None = None) -> dict[str, Any]:
    spec = resolve_workflow(session, settings, "ASK_PLANNER", planner_provider)
    planner = build_provider(spec, settings)
    ask = AskService(session, settings, inline=True)
    plan = ask._plan(planner, question)
    search = SearchService(session, settings)
    answer_spec = resolve_workflow(session, settings, "ASK_ANSWER", None)
    privacy = ["PUBLIC", "PRIVATE", "SENSITIVE"] if answer_spec.is_local else ["PUBLIC", "PRIVATE"]
    started = time.perf_counter()
    try:
        if plan["mode"] == COVERAGE:
            covered = search.cover(question, {"eligible_privacy": privacy})
            hits = [item for item in covered["hits"] if item.get("chunk_id")]
            meta = {
                "retrieval_mode": COVERAGE,
                "eligible_source_count": covered["eligible_source_count"],
                "retrieved_source_count": covered["retrieved_source_count"],
            }
        else:
            allowed = search.search(question, {"eligible_privacy": privacy}, mode="hybrid")
            hits = [item for item in allowed["results"] if item.get("chunk_id")]
            meta = {"retrieval_mode": "FOCUSED", "eligible_source_count": len(hits), "retrieved_source_count": len(hits)}
    except EmbeddingError as exc:
        raise RuntimeError("RETRIEVAL_DEPENDENCY_UNAVAILABLE") from exc
    meta["retrieval_latency_ms"] = int((time.perf_counter() - started) * 1000)
    context = ask._pack(hits, expand_neighbors=plan["mode"] != COVERAGE)
    return {
        "question": question,
        "plan": plan,
        "meta": meta,
        "context": [
            {
                "chunk_id": str(item["chunk"].id),
                "source_id": str(item["source_id"]),
                "role": item.get("role"),
                "score": item.get("score"),
                "retrieval_reason": item.get("retrieval_reason"),
            }
            for item in context
        ],
    }


def _hydrate_context(session: Session, packet: dict[str, Any]) -> list[dict]:
    context = []
    for item in packet["context"]:
        chunk = session.get(ContentChunk, uuid.UUID(item["chunk_id"]))
        if chunk is None:
            continue
        document = session.get(ExtractedDocument, chunk.extracted_document_id)
        source = session.get(SourceItem, document.source_item_id) if document else None
        if source is None:
            continue
        context.append(
            {
                "chunk": chunk,
                "role": item.get("role") or "hit",
                "score": item.get("score") or 0,
                "source": source,
                "source_id": source.id,
                "retrieval_reason": item.get("retrieval_reason") or "RELEVANCE",
            }
        )
    return context


def answer_from_packet(session: Session, settings: Settings, packet: dict[str, Any], answer_provider: str) -> dict[str, Any]:
    ask = AskService(session, settings, inline=True)
    context = _hydrate_context(session, packet)
    meta = dict(packet.get("meta") or {})
    plan = packet.get("plan") or {}
    question = packet["question"]
    evidence = ask._evidence(context)
    system = (PROJECT_ROOT / "prompts" / "ask" / "v1" / "system.md").read_text(encoding="utf-8")
    user = (PROJECT_ROOT / "prompts" / "ask" / "v1" / "user.md").read_text(encoding="utf-8")
    user = (
        user.replace("{{question}}", question)
        .replace("{{mode}}", meta.get("retrieval_mode", "FOCUSED"))
        .replace("{{eligible_count}}", str(meta.get("eligible_source_count") or 0))
        .replace("{{retrieved_count}}", str(meta.get("retrieved_source_count") or 0))
        .replace("{{coverage_complete}}", "not_applicable")
        .replace("{{missing_sources}}", "none")
        .replace("{{evidence}}", evidence)
    )
    spec = resolve_workflow(session, settings, "ASK_ANSWER", answer_provider)
    provider = build_provider(spec, settings)
    started = time.perf_counter()
    try:
        response = provider.complete(
            LLMRequest(
                system_prompt=system,
                user_content=user,
                response_schema=ANSWER_SCHEMA if getattr(provider, "supports_json_schema", False) else None,
                temperature=0,
                max_output_tokens=settings.analysis_max_output_tokens,
                metadata={"purpose": "ask_answer", "schema_name": "ask_answer"},
            )
        )
    except LLMError as exc:
        return {
            "status": "FAILED",
            "error_code": exc.code,
            "provider": spec.provider_type,
            "model": spec.model,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    latency = int((time.perf_counter() - started) * 1000)
    try:
        payload = extract_json_object(response.text)
    except (ValueError, json.JSONDecodeError):
        return {
            "status": "FAILED",
            "error_code": "STRUCTURED_OUTPUT_INVALID",
            "provider": spec.provider_type,
            "model": response.model,
            "latency_ms": latency,
        }
    answer = payload.get("answer") if isinstance(payload.get("answer"), str) else ""
    citations = payload.get("citations") if isinstance(payload.get("citations"), list) else []
    allowed = {str(item["chunk"].id): item for item in context}
    valid = 0
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        chunk_id = str(citation.get("chunk_id") or "")
        quote = str(citation.get("quote") or "")
        item = allowed.get(chunk_id)
        if item is None:
            continue
        normalized = " ".join(item["chunk"].content.split())
        if quote and " ".join(quote.split()) in normalized:
            valid += 1
    status = "SUCCEEDED" if valid > 0 else "PARTIAL"
    error_code = None if valid > 0 else "NO_VALIDATED_CITATIONS"
    return {
        "status": status,
        "error_code": error_code,
        "provider": spec.provider_type,
        "model": response.model,
        "latency_ms": latency,
        "prompt_tokens": response.input_tokens,
        "completion_tokens": response.output_tokens,
        "citation_count": len(citations),
        "validated_citations": valid,
        "answer_chars": len(answer),
    }
