"""Auto cover eligibility, funnel audit, and enqueue (no silent paid calls in tests)."""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.services.cover.settings_prefs import load_cover_prefs
from app.models.analysis import AnalysisRun
from app.models.cover import CoverGenerationRun, SourceCoverAsset
from app.models.extraction import ExtractedDocument, ExtractionRun
from app.models.source_item import SourceItem
from app.services.cover.resolution import library_has_cover
from app.services.cover.service import ACTIVE_STATUSES, CoverGenerationService, CoverServiceError
from app.services.cover.budget import monthly_budget_usage_count
from app.services.system_scope import USER_SCOPE


class CoverFunnelRow:
    def __init__(self, bucket: str, count: int, sample_source_ids: list[str]) -> None:
        self.bucket = bucket
        self.count = count
        self.sample_source_ids = sample_source_ids


def _month_start(now: datetime) -> datetime:
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


def monthly_generated_count(session: Session, *, settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    now = datetime.now(timezone.utc)
    start = _month_start(now)
    return int(
        session.scalar(
            select(func.count())
            .select_from(CoverGenerationRun)
            .join(SourceItem, SourceItem.id == CoverGenerationRun.source_item_id)
            .where(
                SourceItem.system_scope == USER_SCOPE,
                CoverGenerationRun.status == "SUCCEEDED",
                CoverGenerationRun.created_at >= start,
            )
        )
        or 0
    )


def _latest_analysis(session: Session, source_id: uuid.UUID) -> AnalysisRun | None:
    return session.scalar(
        select(AnalysisRun).where(AnalysisRun.source_item_id == source_id).order_by(AnalysisRun.created_at.desc()).limit(1)
    )


def _latest_extraction(session: Session, source_id: uuid.UUID) -> ExtractionRun | None:
    return session.scalar(
        select(ExtractionRun).where(ExtractionRun.source_item_id == source_id).order_by(ExtractionRun.created_at.desc()).limit(1)
    )


def classify_source_cover_bucket(session: Session, source: SourceItem, *, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    prefs = load_cover_prefs(session, settings)
    if source.deleted_at is not None:
        return "deleted"
    doc = session.scalar(
        select(ExtractedDocument).where(ExtractedDocument.source_item_id == source.id).order_by(ExtractedDocument.created_at.desc())
    )
    if library_has_cover(session, source.id, doc):
        return "has_cover"
    extraction = _latest_extraction(session, source.id)
    if extraction is None or extraction.status not in {"SUCCEEDED", "PARTIAL"}:
        return "not_eligible_extraction"
    analysis = _latest_analysis(session, source.id)
    if prefs.requires_analysis:
        if analysis is None or analysis.status not in {"SUCCEEDED", "PARTIAL"}:
            return "not_eligible_analysis"
        if source.system_scope == USER_SCOPE and (analysis.provider_type == "FAKE" or analysis.model_name == "fake-model"):
            return "not_eligible_analysis"
    active = session.scalar(
        select(CoverGenerationRun)
        .where(CoverGenerationRun.source_item_id == source.id, CoverGenerationRun.status.in_(ACTIVE_STATUSES))
        .order_by(CoverGenerationRun.created_at.desc())
    )
    if active is not None:
        return "generating"
    latest = session.scalar(
        select(CoverGenerationRun)
        .where(CoverGenerationRun.source_item_id == source.id)
        .order_by(CoverGenerationRun.created_at.desc())
    )
    if latest is not None and latest.status == "FAILED":
        return "failed"
    if latest is not None and latest.status == "SUCCEEDED" and latest.asset_id is not None:
        # A saved candidate is already a completed paid attempt. Waiting for
        # human review must not enqueue another automatic generation.
        return "candidate_saved"
    if latest is not None and latest.status in {"QUEUED", "GENERATING"}:
        return "queued"
    used = monthly_budget_usage_count(session)
    if used >= prefs.monthly_budget:
        return "budget_limited"
    if doc and doc.metadata_json and isinstance(doc.metadata_json, dict):
        if doc.metadata_json.get("preview_image_url"):
            return "web_preview_only"
    return "eligible_missing_cover"


def audit_cover_funnel(session: Session, *, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    prefs = load_cover_prefs(session, settings)
    sources = list(
        session.scalars(select(SourceItem).where(SourceItem.system_scope == USER_SCOPE, SourceItem.deleted_at.is_(None))).all()
    )
    counts: Counter[str] = Counter()
    samples: dict[str, list[str]] = {}
    for source in sources:
        bucket = classify_source_cover_bucket(session, source, settings=settings)
        counts[bucket] += 1
        samples.setdefault(bucket, [])
        if len(samples[bucket]) < 5:
            samples[bucket].append(str(source.id))
    return {
        "total_sources": len(sources),
        "buckets": {key: {"count": counts[key], "sample_source_ids": samples.get(key, [])} for key in sorted(counts.keys())},
        "monthly_budget": prefs.monthly_budget,
        "budget_kind": "insighthub_local_safety_cap",
        "monthly_attempts": monthly_budget_usage_count(session),
        "monthly_used": monthly_budget_usage_count(session),
        "monthly_successful": monthly_generated_count(session, settings=settings),
        "auto_enabled": prefs.auto_enabled,
        "requires_analysis": prefs.requires_analysis,
    }


def scan_and_enqueue_auto_covers(session: Session, *, settings: Settings | None = None, limit: int = 50) -> dict:
    """Idempotent batch enqueue for eligible sources when auto cover is enabled."""
    settings = settings or get_settings()
    prefs = load_cover_prefs(session, settings)
    if not prefs.auto_enabled:
        return {"ok": True, "enqueued": 0, "skipped": {"auto_disabled": 1}}
    used = monthly_budget_usage_count(session)
    remaining = max(0, prefs.monthly_budget - used)
    if remaining <= 0:
        return {"ok": True, "enqueued": 0, "skipped": {"budget_limited": 1}, "monthly_used": used}
    sources = list(
        session.scalars(select(SourceItem).where(SourceItem.system_scope == USER_SCOPE, SourceItem.deleted_at.is_(None))).all()
    )
    enqueued = 0
    skipped: Counter[str] = Counter()
    for source in sources:
        if enqueued >= min(limit, remaining):
            skipped["scan_limit"] += 1
            continue
        bucket = classify_source_cover_bucket(session, source, settings=settings)
        if bucket != "eligible_missing_cover":
            skipped[bucket] += 1
            continue
        run = maybe_enqueue_auto_cover(session, source.id, settings=settings)
        if run is not None:
            enqueued += 1
        else:
            skipped["enqueue_failed"] += 1
    return {"ok": True, "enqueued": enqueued, "skipped": dict(skipped), "monthly_used": used}


def maybe_enqueue_auto_cover(session: Session, source_id: uuid.UUID, *, settings: Settings | None = None) -> CoverGenerationRun | None:
    settings = settings or get_settings()
    prefs = load_cover_prefs(session, settings)
    if not prefs.auto_enabled:
        return None
    source = session.get(SourceItem, source_id)
    if source is None or source.system_scope != USER_SCOPE or source.deleted_at is not None:
        return None
    bucket = classify_source_cover_bucket(session, source, settings=settings)
    if bucket != "eligible_missing_cover":
        return None
    service = CoverGenerationService(session, settings=settings)
    try:
        return service.enqueue(source_id, prompt=None, confirm_send=True, auto=True)
    except CoverServiceError:
        return None


def enqueue_backfill_missing(
    session: Session,
    *,
    source_ids: list[uuid.UUID] | None,
    confirm: bool,
    retry_failed_only: bool,
    settings: Settings | None = None,
) -> dict:
    settings = settings or get_settings()
    if not confirm:
        raise CoverServiceError("CONFIRMATION_REQUIRED", "批量补图需要确认。", 400)
    service = CoverGenerationService(session, settings=settings)
    targets: list[uuid.UUID] = []
    if source_ids:
        targets = source_ids
    else:
        sources = session.scalars(select(SourceItem).where(SourceItem.system_scope == USER_SCOPE, SourceItem.deleted_at.is_(None))).all()
        for source in sources:
            bucket = classify_source_cover_bucket(session, source, settings=settings)
            if retry_failed_only:
                if bucket == "failed":
                    targets.append(source.id)
            elif bucket == "eligible_missing_cover":
                targets.append(source.id)
    enqueued: list[str] = []
    skipped: Counter[str] = Counter()
    for sid in targets:
        bucket = classify_source_cover_bucket(session, session.get(SourceItem, sid), settings=settings)
        if retry_failed_only and bucket != "failed":
            skipped[bucket] += 1
            continue
        if not retry_failed_only and bucket != "eligible_missing_cover":
            skipped[bucket] += 1
            continue
        try:
            run = service.enqueue(sid, prompt=None, confirm_send=True, auto=True)
            enqueued.append(str(run.id))
        except CoverServiceError as exc:
            skipped[exc.code] += 1
    return {"enqueued_run_ids": enqueued, "skipped": dict(skipped), "requested": len(targets)}
