"""Read-only USER source pipeline funnel and failure taxonomy (M-PIPELINE-R1 Phase A)."""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.analysis import AnalysisResult, AnalysisRun, Claim, Evidence
from app.models.cover import SourceCoverAsset
from app.models.extraction import ExtractedDocument, ExtractionRun
from app.models.ingestion_record import IngestionRecord
from app.models.organization import Category, SourceCategoryAssignment
from app.models.source_asset import SourceAsset
from app.models.source_item import SourceItem
from app.services.cover.resolution import library_has_cover, resolve_cover
from app.services.extraction_status import extraction_status_for_source
from app.services.research_note import analysis_status_for_source
from app.services.synthesis.service import SynthesisService

USER_SCOPE = "USER"


def _map_analysis_error(code: str | None) -> str:
    if not code:
        return "INTERNAL_ERROR"
    mapping = {
        "SOURCE_NOT_EXTRACTED": "NO_USABLE_CONTENT",
        "ANALYSIS_SOURCE_CONTENT_EMPTY": "NO_USABLE_CONTENT",
        "CONTEXT_TOO_LARGE": "CONTEXT_TOO_LONG",
        "STRUCTURED_OUTPUT_INVALID": "INVALID_JSON",
        "SCHEMA_VALIDATION_FAILED": "SCHEMA_VALIDATION_FAILED",
        "EVIDENCE_VALIDATION_FAILED": "EVIDENCE_VALIDATION_FAILED",
        "PRIVACY_PROVIDER_NOT_ALLOWED": "PRIVACY_BLOCKED",
        "PROVIDER_NOT_CONFIGURED": "PROVIDER_NOT_CONFIGURED",
        "PROVIDER_UNAVAILABLE": "PROVIDER_HTTP_ERROR",
        "TIMEOUT": "PROVIDER_TIMEOUT",
        "RATE_LIMITED": "RATE_LIMIT",
        "AUTH_FAILED": "AUTH_FAILED",
        "INSUFFICIENT_BALANCE": "INSUFFICIENT_BALANCE",
        "WORKER_NOT_CONSUMING": "QUEUE_NOT_CONSUMED",
        "WORKER_INTERRUPTED": "WORKER_INTERRUPTED",
    }
    return mapping.get(code, code if code.isupper() and len(code) < 48 else "INTERNAL_ERROR")


def _map_extraction_error(code: str | None, status: str | None) -> str:
    if status in {"PENDING", "RUNNING"}:
        return "QUEUE_NOT_CONSUMED"
    if status == "FAILED":
        if not code:
            return "EXTRACTION_FAILED"
        web = {
            "WEB_EMPTY": "NO_USABLE_CONTENT",
            "WEB_EXTRACTION_LOW_QUALITY": "NO_USABLE_CONTENT",
            "WEB_HTTP_ERROR": "EXTRACTION_FAILED",
            "WEB_TIMEOUT": "EXTRACTION_FAILED",
            "SSRF_BLOCKED": "EXTRACTION_FAILED",
            "BROWSER_SSRF_BLOCKED": "EXTRACTION_FAILED",
            "WEB_AUTH_OR_CHALLENGE": "EXTRACTION_FAILED",
            "BROWSER_AUTH_REQUIRED": "EXTRACTION_FAILED",
            "BROWSER_CHALLENGE_DETECTED": "EXTRACTION_FAILED",
            "WORKER_NOT_CONSUMING": "QUEUE_NOT_CONSUMED",
            "WORKER_INTERRUPTED": "WORKER_INTERRUPTED",
        }
        return web.get(code, "EXTRACTION_FAILED")
    if status in {"SAVED", None}:
        return "ANALYSIS_NOT_STARTED"
    return "EXTRACTION_FAILED"


@dataclass
class SourceAuditRow:
    source_id: uuid.UUID
    source_type: str
    problem_class: str
    extraction_code: str | None
    analysis_code: str | None
    taxonomy: str
    historical_failed_runs: int = 0


def _current_extraction(session: Session, source_id: uuid.UUID) -> ExtractionRun | None:
    row = session.scalar(select(ExtractionRun).where(ExtractionRun.source_item_id == source_id, ExtractionRun.is_current.is_(True)))
    if row is not None:
        return row
    return session.scalar(
        select(ExtractionRun).where(ExtractionRun.source_item_id == source_id).order_by(ExtractionRun.created_at.desc()).limit(1)
    )


def _current_analysis(session: Session, source_id: uuid.UUID) -> AnalysisRun | None:
    row = session.scalar(select(AnalysisRun).where(AnalysisRun.source_item_id == source_id, AnalysisRun.is_current.is_(True)))
    if row is not None:
        return row
    return session.scalar(
        select(AnalysisRun).where(AnalysisRun.source_item_id == source_id).order_by(AnalysisRun.created_at.desc()).limit(1)
    )


def _content_analysis(session: Session, source_id: uuid.UUID) -> AnalysisRun | None:
    source = session.get(SourceItem, source_id)
    stmt = select(AnalysisRun).where(
        AnalysisRun.source_item_id == source_id,
        AnalysisRun.status.in_(("SUCCEEDED", "PARTIAL")),
    )
    if source is not None and source.system_scope == USER_SCOPE:
        stmt = stmt.where(AnalysisRun.provider_type != "FAKE", AnalysisRun.model_name != "fake-model")
    return session.scalar(stmt.order_by(AnalysisRun.is_current.desc(), AnalysisRun.created_at.desc()).limit(1))


def _has_claims_evidence(session: Session, run: AnalysisRun | None) -> bool:
    if run is None or run.status not in {"SUCCEEDED", "PARTIAL"}:
        return False
    result = session.scalar(select(AnalysisResult).where(AnalysisResult.analysis_run_id == run.id))
    if result is None:
        return False
    claim = session.scalar(select(Claim.id).where(Claim.analysis_result_id == result.id).limit(1))
    if claim is None:
        return False
    return session.scalar(select(Evidence.id).join(Claim, Evidence.claim_id == Claim.id).where(Claim.analysis_result_id == result.id).limit(1)) is not None


def classify_source(session: Session, source_id: uuid.UUID, synthesis: SynthesisService | None = None) -> SourceAuditRow:
    source = session.get(SourceItem, source_id)
    assert source is not None
    ext = extraction_status_for_source(session, source_id)
    ext_code = ext["extraction_status_code"]
    ext_err = ext.get("extraction_error_code")
    extraction = _current_extraction(session, source_id)
    latest_analysis = session.scalar(
        select(AnalysisRun).where(AnalysisRun.source_item_id == source_id).order_by(AnalysisRun.created_at.desc()).limit(1)
    )
    latest_analysis_is_fake = bool(latest_analysis and (latest_analysis.provider_type == "FAKE" or latest_analysis.model_name == "fake-model"))
    content = _content_analysis(session, source_id)
    current = _current_analysis(session, source_id)
    hist_failed = int(
        session.scalar(
            select(func.count()).select_from(AnalysisRun).where(AnalysisRun.source_item_id == source_id, AnalysisRun.status == "FAILED")
        )
        or 0
    )

    usable = ext.get("has_usable_content") and ext_code in {"SUCCEEDED", "PARTIAL"}
    if not usable and ext_code in {"FAILED", "WORKER_NOT_CONSUMING", "SAVED"}:
        problem = "extraction"
        taxonomy = _map_extraction_error(ext_err or extraction.error_code if extraction else None, ext_code if ext_code != "WORKER_NOT_CONSUMING" else extraction.status if extraction else None)
    elif latest_analysis_is_fake and content is None:
        problem = "analysis_failed"
        taxonomy = "FAKE_RESULT_UNTRUSTED"
    elif latest_analysis is None:
        problem = "not_analyzed"
        taxonomy = "ANALYSIS_NOT_STARTED"
    elif latest_analysis.status in {"PENDING", "QUEUED", "RUNNING"}:
        problem = "in_progress"
        taxonomy = "QUEUE_NOT_CONSUMED" if latest_analysis.status in {"PENDING", "QUEUED"} else "INTERNAL_ERROR"
    elif content is None and (current is None or current.status == "FAILED"):
        problem = "analysis_failed"
        taxonomy = _map_analysis_error((current or latest_analysis).error_code)
    elif content is not None and _has_claims_evidence(session, content):
        problem = "ready"
        taxonomy = "READY"
    elif content is not None:
        problem = "analysis_partial"
        taxonomy = "EVIDENCE_VALIDATION_FAILED"
    else:
        problem = "not_analyzed"
        taxonomy = "ANALYSIS_NOT_STARTED"

    if synthesis is not None and problem == "ready":
        ok, reason = synthesis._ready(source_id)  # noqa: SLF001 — audit reuses brief eligibility
        if not ok and reason == "NO_ANALYSIS":
            problem = "not_analyzed"
            taxonomy = "ANALYSIS_NOT_STARTED"

    return SourceAuditRow(
        source_id=source_id,
        source_type=source.source_type,
        problem_class=problem,
        extraction_code=ext_code,
        analysis_code=(current or latest_analysis).error_code if (current or latest_analysis) else None,
        taxonomy=taxonomy,
        historical_failed_runs=hist_failed,
    )


def audit_user_sources(session: Session, settings) -> dict[str, Any]:
    synthesis = SynthesisService(session, settings)
    sources = list(
        session.scalars(
            select(SourceItem).where(SourceItem.system_scope == USER_SCOPE, SourceItem.deleted_at.is_(None)).order_by(SourceItem.created_at.asc())
        )
    )
    by_type = Counter(s.source_type for s in sources)
    category_counts: Counter[str] = Counter()
    for source in sources:
        slugs = list(
            session.scalars(
                select(Category.slug)
                .join(SourceCategoryAssignment, SourceCategoryAssignment.category_id == Category.id)
                .where(SourceCategoryAssignment.source_item_id == source.id, SourceCategoryAssignment.status == "ACTIVE")
            )
        )
        if slugs:
            for slug in slugs:
                category_counts[slug] += 1
        else:
            category_counts["(uncategorized)"] += 1

    asset_count = int(
        session.scalar(
            select(func.count())
            .select_from(SourceAsset)
            .join(SourceItem, SourceItem.id == SourceAsset.source_item_id)
            .where(SourceItem.system_scope == USER_SCOPE, SourceItem.deleted_at.is_(None))
        )
        or 0
    )

    extraction_current = Counter()
    extraction_latest = Counter()
    analysis_current_status = Counter()
    analysis_latest_status = Counter()
    provider_failures: Counter[str] = Counter()
    error_taxonomy: Counter[str] = Counter()
    provider_type_failures: Counter[str] = Counter()
    problem_classes: Counter[str] = Counter()
    cover_stats = Counter()
    brief_eligible = 0
    claims_ok = 0
    extraction_ok = 0
    analysis_ok = 0
    never_analysis = 0
    rows: list[SourceAuditRow] = []

    for source in sources:
        row = classify_source(session, source.id, synthesis)
        rows.append(row)
        problem_classes[row.problem_class] += 1
        error_taxonomy[row.taxonomy] += 1

        cur_ext = session.scalar(select(ExtractionRun).where(ExtractionRun.source_item_id == source.id, ExtractionRun.is_current.is_(True)))
        if cur_ext:
            extraction_current[cur_ext.status] += 1
        lat_ext = session.scalar(select(ExtractionRun).where(ExtractionRun.source_item_id == source.id).order_by(ExtractionRun.created_at.desc()).limit(1))
        if lat_ext:
            extraction_latest[lat_ext.status] += 1

        cur_a = session.scalar(select(AnalysisRun).where(AnalysisRun.source_item_id == source.id, AnalysisRun.is_current.is_(True)))
        if cur_a:
            analysis_current_status[cur_a.status] += 1
        lat_a = session.scalar(select(AnalysisRun).where(AnalysisRun.source_item_id == source.id).order_by(AnalysisRun.created_at.desc()).limit(1))
        if lat_a:
            analysis_latest_status[lat_a.status] += 1
        if lat_a is None:
            never_analysis += 1

        if synthesis._extraction_ready(source.id)[0]:  # noqa: SLF001
            extraction_ok += 1
        if synthesis._ready(source.id)[0]:  # noqa: SLF001
            analysis_ok += 1
        if synthesis._has_claims(source.id):  # noqa: SLF001
            claims_ok += 1
        if synthesis._ready(source.id)[0] and synthesis._has_claims(source.id):  # noqa: SLF001
            brief_eligible += 1

        doc = session.scalar(select(ExtractedDocument).where(ExtractedDocument.source_item_id == source.id).order_by(ExtractedDocument.created_at.desc()).limit(1))
        if library_has_cover(session, source.id, doc):
            resolved = resolve_cover(session, source.id, doc)
            cover_stats[resolved.kind if resolved else "unknown"] += 1
        else:
            cover_stats["none"] += 1

        for failed in session.scalars(
            select(AnalysisRun).where(AnalysisRun.source_item_id == source.id, AnalysisRun.status == "FAILED")
        ):
            key = f"{failed.provider_type}:{failed.error_code or 'UNKNOWN'}"
            provider_failures[key] += 1
            provider_type_failures[failed.provider_type or "UNKNOWN"] += 1

    current_success_analysis = int(analysis_current_status.get("SUCCEEDED", 0) + analysis_current_status.get("PARTIAL", 0))
    latest_failed = int(analysis_latest_status.get("FAILED", 0))
    content_success_but_latest_failed = sum(1 for r in rows if r.problem_class == "ready" and r.historical_failed_runs > 0)

    extraction_failed = sum(1 for r in rows if r.problem_class == "extraction")
    analysis_failed = sum(1 for r in rows if r.problem_class == "analysis_failed")
    not_analyzed = sum(1 for r in rows if r.problem_class == "not_analyzed")
    batch_candidates = sum(1 for r in rows if r.problem_class in {"not_analyzed", "analysis_failed"} and r.extraction_code in {"SUCCEEDED", "PARTIAL"})

    deepseek_only_failures = sum(
        count for key, count in provider_failures.items() if key.startswith("DEEPSEEK:")
    )
    total_failed_runs = sum(provider_failures.values())

    return {
        "scope": USER_SCOPE,
        "source_total": len(sources),
        "by_source_type": dict(by_type),
        "by_category_slug": dict(category_counts.most_common(50)),
        "source_asset_count": asset_count,
        "extraction_current_status": dict(extraction_current),
        "extraction_latest_status": dict(extraction_latest),
        "analysis_current_status": dict(analysis_current_status),
        "analysis_latest_status": dict(analysis_latest_status),
        "funnel": {
            "extraction_ready": extraction_ok,
            "analysis_ready": analysis_ok,
            "claims_ready": claims_ok,
            "brief_eligible": brief_eligible,
            "with_cover": sum(c for k, c in cover_stats.items() if k != "none"),
            "cover_none": cover_stats.get("none", 0),
            "cover_by_kind": dict(cover_stats),
        },
        "analysis_never_started": never_analysis,
        "problem_class_counts": dict(problem_classes),
        "standard_taxonomy_counts": dict(error_taxonomy.most_common()),
        "analysis_failed_runs_by_provider_error": dict(provider_failures.most_common(40)),
        "analysis_failed_runs_by_provider": dict(provider_type_failures),
        "totals": {
            "extraction_failed_sources": extraction_failed,
            "analysis_failed_sources": analysis_failed,
            "not_analyzed_sources": not_analyzed,
            "batch_analysis_candidates_extraction_ok": batch_candidates,
            "current_analysis_success_sources": current_success_analysis,
            "latest_run_failed_sources": latest_failed,
            "sources_with_historic_failures_but_current_ok": content_success_but_latest_failed,
            "total_failed_analysis_runs": total_failed_runs,
            "deepseek_failed_run_events": deepseek_only_failures,
        },
        "gate_a_conclusion": {
            "deepseek_is_primary_coverage_blocker": not_analyzed <= analysis_failed
            and deepseek_only_failures >= total_failed_runs // 2
            and analysis_failed > extraction_failed,
            "primary_coverage_gap": (
                "ANALYSIS_NOT_STARTED"
                if not_analyzed >= max(analysis_failed, extraction_failed, 1)
                else ("EXTRACTION_FAILED" if extraction_failed >= analysis_failed else "ANALYSIS_FAILED")
            ),
            "evidence_summary": (
                f"not_analyzed={not_analyzed}, analysis_failed_sources={analysis_failed}, "
                f"extraction_failed={extraction_failed}, deepseek_failed_run_events={deepseek_only_failures}, "
                f"total_failed_runs={total_failed_runs}"
            ),
        },
    }
