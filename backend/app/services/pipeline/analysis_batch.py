"""Batch analysis backfill for USER sources (explicit user confirmation)."""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.source_item import SourceItem
from app.services.analysis.service import AnalysisError, AnalysisService
from app.services.cover.auto import monthly_generated_count
from app.services.cover.budget import monthly_budget_usage_count
from app.services.cover.settings_prefs import load_cover_prefs
from app.services.maintenance.pipeline_audit import classify_source
from app.services.maintenance.recovery import recover_stale_jobs
from app.services.synthesis.service import SynthesisService
from app.services.system_scope import USER_SCOPE

BatchMode = Literal["fresh", "retry_failed", "retry_partial"]


class AnalysisBatchError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def preview_analysis_backfill(session: Session, *, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    synthesis = SynthesisService(session, settings)
    sources = list(
        session.scalars(select(SourceItem).where(SourceItem.system_scope == USER_SCOPE, SourceItem.deleted_at.is_(None))).all()
    )
    buckets: Counter[str] = Counter()
    samples: dict[str, list[str]] = {}
    fresh_ids: list[str] = []
    retry_failed_ids: list[str] = []
    retry_partial_ids: list[str] = []
    active_ids: list[str] = []

    for source in sources:
        row = classify_source(session, source.id, synthesis)
        key = row.problem_class
        if row.extraction_code not in {"SUCCEEDED", "PARTIAL"} and row.problem_class in {"not_analyzed", "analysis_failed", "analysis_partial"}:
            key = "extraction_not_ready"
        buckets[key] += 1
        samples.setdefault(key, [])
        if len(samples[key]) < 5:
            samples[key].append(str(source.id))
        if row.problem_class == "in_progress":
            active_ids.append(str(source.id))
            continue
        if row.extraction_code not in {"SUCCEEDED", "PARTIAL"}:
            continue
        if row.problem_class == "not_analyzed":
            fresh_ids.append(str(source.id))
        elif row.problem_class == "analysis_failed":
            retry_failed_ids.append(str(source.id))
        elif row.problem_class == "analysis_partial":
            retry_partial_ids.append(str(source.id))

    prefs = load_cover_prefs(session, settings)
    cover_hint = None
    if prefs.auto_enabled and (fresh_ids or retry_failed_ids):
        remaining = max(0, prefs.monthly_budget - monthly_budget_usage_count(session))
        cover_hint = {
            "auto_cover_enabled": True,
            "monthly_budget": prefs.monthly_budget,
            "monthly_used": monthly_budget_usage_count(session),
            "monthly_successful": monthly_generated_count(session, settings=settings),
            "monthly_remaining": remaining,
            "note": "分析成功后可能按规则自动入队配图（MiniMax 付费），请确认月度预算。",
        }

    explanation = None
    if len(fresh_ids) == 0 and active_ids:
        explanation = f"当前有 {len(active_ids)} 条资料的分析任务已在队列或执行中，因此「未分析」候选为 0。"
    if len(retry_failed_ids) and len(fresh_ids) == 0:
        hint = f"另有 {len(retry_failed_ids)} 条失败资料可重试。"
        explanation = f"{explanation} {hint}".strip() if explanation else hint
    if retry_partial_ids and not explanation:
        explanation = f"另有 {len(retry_partial_ids)} 条部分成功资料可选择重分析。"

    return {
        "total_sources": len(sources),
        "buckets": {k: {"count": buckets[k], "sample_source_ids": samples.get(k, [])} for k in sorted(buckets.keys())},
        "default_candidate_count": len(fresh_ids),
        "default_candidate_source_ids": fresh_ids[:200],
        "fresh_candidate_count": len(fresh_ids),
        "fresh_candidate_source_ids": fresh_ids[:200],
        "retry_failed_count": len(retry_failed_ids),
        "retry_failed_source_ids": retry_failed_ids[:200],
        "retry_partial_count": len(retry_partial_ids),
        "retry_partial_source_ids": retry_partial_ids[:200],
        "active_task_count": len(active_ids),
        "active_source_ids": active_ids[:50],
        "explanation": explanation,
        "cover_side_effect": cover_hint,
    }


def enqueue_analysis_backfill(
    session: Session,
    *,
    source_ids: list[uuid.UUID] | None,
    confirm: bool,
    include_partial: bool,
    mode: BatchMode = "fresh",
    settings: Settings | None = None,
    enqueue_analysis,
) -> dict:
    settings = settings or get_settings()
    if not confirm:
        raise AnalysisBatchError("CONFIRMATION_REQUIRED", "批量分析需要确认启动。", 400)
    recover_stale_jobs(session, settings)
    synthesis = SynthesisService(session, settings)
    preview = preview_analysis_backfill(session, settings=settings)
    if source_ids:
        targets = list(source_ids)
    elif mode == "retry_failed":
        targets = [uuid.UUID(sid) for sid in preview["retry_failed_source_ids"]]
    elif mode == "retry_partial" and include_partial:
        targets = [uuid.UUID(sid) for sid in preview["retry_partial_source_ids"]]
    elif mode == "fresh":
        targets = [uuid.UUID(sid) for sid in preview["fresh_candidate_source_ids"]]
    else:
        targets = [uuid.UUID(sid) for sid in preview["default_candidate_source_ids"]]

    service = AnalysisService(session, inline=settings.analysis_inline, settings=settings, enqueue=enqueue_analysis)
    enqueued: list[str] = []
    skipped: Counter[str] = Counter()
    for sid in targets:
        source = session.get(SourceItem, sid)
        if source is None or source.deleted_at is not None or source.system_scope != USER_SCOPE:
            skipped["source_not_eligible"] += 1
            continue
        row = classify_source(session, sid, synthesis)
        if row.problem_class == "ready":
            skipped["already_succeeded"] += 1
            continue
        if row.problem_class == "in_progress":
            skipped["active_run"] += 1
            continue
        if row.extraction_code not in {"SUCCEEDED", "PARTIAL"}:
            skipped["extraction_not_ready"] += 1
            continue
        if mode == "fresh" and row.problem_class != "not_analyzed":
            skipped["not_fresh"] += 1
            continue
        if mode == "retry_failed" and row.problem_class != "analysis_failed":
            skipped["not_failed"] += 1
            continue
        if mode == "retry_partial" and row.problem_class != "analysis_partial":
            skipped["not_partial"] += 1
            continue
        if row.problem_class == "analysis_partial" and not include_partial and mode != "retry_partial":
            skipped["partial_skipped"] += 1
            continue
        try:
            run = service.start(sid)
            enqueued.append(str(run.id))
        except AnalysisError as exc:
            skipped[exc.code] += 1
    return {
        "enqueued_run_ids": enqueued,
        "skipped": dict(skipped),
        "requested": len(targets),
        "mode": mode,
        "preview_snapshot": {
            "active_task_count": preview.get("active_task_count"),
            "fresh_candidate_count": preview.get("fresh_candidate_count"),
            "retry_failed_count": preview.get("retry_failed_count"),
        },
    }
