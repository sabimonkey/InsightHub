"""Deterministic benchmark metrics. No LLM judge."""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.analysis import AnalysisResult, AnalysisRun, Claim, Evidence
from app.models.extraction import ContentChunk
from app.services.analysis.service import empty_input_summary, semantic_empty_result
from app.services.analysis.schema import SourceAnalysis

_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
_GITHUB_RE = re.compile(r"https?://github\.com/[^\s\"'<>]+", re.I)


def _urls_in_text(text: str) -> set[str]:
    return {item.rstrip(".,);]") for item in _URL_RE.findall(text or "")}


def analysis_run_metrics(session: Session, run: AnalysisRun, chunk_by_id: dict[str, str]) -> dict[str, Any]:
    result = session.scalar(select(AnalysisResult).where(AnalysisResult.analysis_run_id == run.id))
    meta = run.metadata_json or {}
    claims = []
    if result is not None:
        claims = list(session.scalars(select(Claim).where(Claim.analysis_result_id == result.id)))
    parsed: SourceAnalysis | None = None
    parse_ok = False
    schema_ok = False
    if result is not None:
        payload = {k: v for k, v in (result.raw_structured_json or {}).items() if k != "validation_issues"}
        try:
            parsed = SourceAnalysis.model_validate(payload)
            schema_ok = True
            parse_ok = True
        except Exception:
            parsed = None
            schema_ok = False
    summary = (result.summary if result else "") or ""
    semantic_ok = bool(summary.strip()) and not empty_input_summary(summary)
    if parsed is not None and semantic_empty_result(parsed):
        semantic_ok = False
    if parsed is not None and semantic_ok:
        semantic_ok = bool(parsed.facts or parsed.source_claims or parsed.inferences or parsed.hypotheses or parsed.unknowns or parsed.questions)

    corpus_urls: set[str] = set()
    for text in chunk_by_id.values():
        corpus_urls |= _urls_in_text(text)

    hallucinated_urls = 0
    invalid_quotes = 0
    valid_evidence = 0
    fact_count = 0
    source_claim_count = 0
    attribution_flags = 0
    for claim in claims:
        if claim.claim_type == "FACT":
            fact_count += 1
            if "openkb" in (claim.text or "").lower() and "称" not in claim.text and "帖子" not in claim.text and "作者" not in claim.text:
                attribution_flags += 1
        if claim.claim_type == "SOURCE_CLAIM":
            source_claim_count += 1
        for url in _GITHUB_RE.findall(claim.text or ""):
            if url not in corpus_urls and not any(url in c or c in url for c in corpus_urls):
                hallucinated_urls += 1
        evidence_rows = list(session.scalars(select(Evidence).where(Evidence.claim_id == claim.id)))
        for ev in evidence_rows:
            chunk = session.get(ContentChunk, ev.content_chunk_id)
            hay = chunk_by_id.get(str(ev.content_chunk_id), "") if chunk is None else (chunk.content or "")
            quote = (ev.quote_text or "").strip()
            if quote and quote in hay:
                valid_evidence += 1
            elif quote:
                invalid_quotes += 1

    issues = (result.raw_structured_json or {}).get("validation_issues") if result else []
    if isinstance(meta.get("validation_issues"), list):
        issues = list(issues or []) + meta["validation_issues"]
    discarded = len(issues or [])

    return {
        "run_id": str(run.id),
        "provider": run.provider_type,
        "model": run.model_name,
        "status": run.status,
        "error_code": run.error_code,
        "strategy": meta.get("output_strategy"),
        "finish_reason": meta.get("finish_reason"),
        "http_success": run.status in {"SUCCEEDED", "PARTIAL", "FAILED"} and run.error_code not in {"PROVIDER_UNAVAILABLE", "TIMEOUT"},
        "parse_success": parse_ok,
        "schema_success": schema_ok,
        "semantic_success": semantic_ok and run.status in {"SUCCEEDED", "PARTIAL"},
        "latency_ms": run.latency_ms,
        "prompt_tokens": run.input_tokens,
        "completion_tokens": run.output_tokens,
        "total_tokens": run.total_tokens,
        "claim_count": len(claims),
        "fact_count": fact_count,
        "source_claim_count": source_claim_count,
        "valid_evidence": valid_evidence,
        "invalid_quotes": invalid_quotes,
        "discarded_claims": discarded,
        "hallucinated_url_count": hallucinated_urls,
        "attribution_risk_facts": attribution_flags,
        "summary_chars": len(summary),
    }


def aggregate_numeric(rows: list[dict], key: str) -> float | None:
    values = [row[key] for row in rows if row.get(key) is not None]
    if not values:
        return None
    return sum(values) / len(values)


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2
