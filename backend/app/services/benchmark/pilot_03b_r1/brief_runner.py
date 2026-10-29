"""Brief benchmark without persisting USER-scope Brief rows."""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.llm.routing import resolve_workflow
from app.services.synthesis.service import SynthesisService


def capture_brief_packets(session: Session, settings: Settings, filters: dict) -> tuple[list[dict], list[dict], dict]:
    service = SynthesisService(session, settings, inline=True)
    frozen = dict(filters)
    source_filter = frozen.pop("benchmark_source_ids", None)
    rows = service._selection(frozen)
    if source_filter:
        allowed = {uuid.UUID(item) for item in source_filter}
        rows = [row for row in rows if row["source_id"] in allowed]
    included = [row for row in rows if row["included"]]
    packets = [service._packet(row["source_id"]) for row in included]
    packets = [item for item in packets if item.get("items")]
    meta = {
        "preview_sources": len(rows),
        "preview_included": len(included),
        "packet_count": len(packets),
    }
    return packets, included, meta


def run_brief_with_packets(
    session: Session,
    settings: Settings,
    filters: dict,
    packets: list[dict],
    included_rows: list[dict],
    provider_type: str,
) -> dict[str, Any]:
    service = SynthesisService(session, settings, inline=True)
    frozen = dict(filters)
    frozen.pop("benchmark_source_ids", None)
    spec = resolve_workflow(session, settings, "BRIEF", provider_type)
    if spec is None:
        return {"status": "FAILED", "error_code": "PROVIDER_NOT_CONFIGURED"}
    prompt_name = service._prompt_name(service._frozen_filters(frozen))
    detail = frozen.get("detail_level") or "STANDARD"
    started = time.perf_counter()
    try:
        payload, usage = service._generate(spec, prompt_name, detail, packets, sensitive=False)
    except Exception as exc:
        code = getattr(exc, "code", type(exc).__name__)
        return {"status": "FAILED", "error_code": code, "provider": provider_type, "latency_ms": int((time.perf_counter() - started) * 1000)}
    validated, dropped = service._validate(payload, {row["source_id"] for row in included_rows})
    has_points = service._has_points(validated)
    latency = int((time.perf_counter() - started) * 1000)
    status = "SUCCEEDED" if has_points and not dropped else ("PARTIAL" if has_points else "FAILED")
    error_code = None
    if status == "FAILED":
        error_code = "CITATION_VALIDATION_FAILED"
    elif status == "PARTIAL":
        error_code = "PARTIAL_CONTENT"
    body = validated.get("executive_summary") or ""
    return {
        "status": status,
        "error_code": error_code,
        "provider": usage.get("actual_provider") or spec.provider_type,
        "model": usage.get("model") or spec.model,
        "latency_ms": latency,
        "prompt_tokens": usage.get("input_tokens"),
        "completion_tokens": usage.get("output_tokens"),
        "dropped_citations": bool(dropped),
        "body_chars": len(body),
        "has_points": has_points,
        "output_strategy": usage.get("output_strategy"),
    }
