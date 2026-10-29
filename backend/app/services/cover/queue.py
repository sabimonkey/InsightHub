"""Cover job queue views for settings UI."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.cover import CoverGenerationRun
from app.models.source_item import SourceItem
from app.services.cover.service import ACTIVE_STATUSES
from app.services.cover.settings_prefs import load_cover_prefs
from app.services.cover.auto import monthly_generated_count
from app.services.cover.budget import monthly_budget_usage_count
from app.services.cover.verification import effective_run_success
from app.services.system_scope import USER_SCOPE
from app.core.config import get_settings


def cover_queue_summary(session: Session) -> dict:
    prefs = load_cover_prefs(session)
    counts: dict[str, int] = {}
    for status in ("QUEUED", "GENERATING", "DECODING", "VALIDATING", "SAVING", "SUCCEEDED", "FAILED"):
        counts[status] = int(
            session.scalar(
                select(func.count())
                .select_from(CoverGenerationRun)
                .join(SourceItem, SourceItem.id == CoverGenerationRun.source_item_id)
                .where(SourceItem.system_scope == USER_SCOPE, CoverGenerationRun.status == status)
            )
            or 0
        )
    active = sum(counts.get(s, 0) for s in ACTIVE_STATUSES)
    used = monthly_budget_usage_count(session)
    return {
        "active": active,
        "queued": counts.get("QUEUED", 0),
        "generating": counts.get("GENERATING", 0) + counts.get("DECODING", 0) + counts.get("VALIDATING", 0) + counts.get("SAVING", 0),
        "succeeded": counts.get("SUCCEEDED", 0),
        "failed": counts.get("FAILED", 0),
        "monthly_used": used,
        "monthly_attempts": used,
        "monthly_budget": prefs.monthly_budget,
        "budget_kind": "insighthub_local_safety_cap",
        "monthly_successful": monthly_generated_count(session),
        "auto_enabled": prefs.auto_enabled,
    }


def list_cover_jobs(session: Session, *, limit: int = 40) -> list[dict]:
    rows = list(
        session.scalars(
            select(CoverGenerationRun)
            .join(SourceItem, SourceItem.id == CoverGenerationRun.source_item_id)
            .where(SourceItem.system_scope == USER_SCOPE)
            .order_by(CoverGenerationRun.updated_at.desc())
            .limit(max(1, min(limit, 100)))
        ).all()
    )
    items: list[dict] = []
    for run in rows:
        source = session.get(SourceItem, run.source_item_id)
        ok, err = effective_run_success(session, run)
        can_retry = run.status == "FAILED" and not ok and source is not None and source.deleted_at is None
        if can_retry:
            active = session.scalar(
                select(CoverGenerationRun.id)
                .where(
                    CoverGenerationRun.source_item_id == run.source_item_id,
                    CoverGenerationRun.status.in_(ACTIVE_STATUSES),
                )
                .limit(1)
            )
            can_retry = active is None
        items.append(
            {
                "run_id": str(run.id),
                "source_id": str(run.source_item_id),
                "source_title": source.display_name if source else "—",
                "status": run.status,
                "stage": run.stage,
                "terminal_success": ok,
                "error_code": run.error_code if not ok else None,
                "error_message": run.error_message if not ok else (err if run.status == "SUCCEEDED" else None),
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "updated_at": run.updated_at.isoformat() if run.updated_at else None,
                "is_active": run.status in ACTIVE_STATUSES,
                "can_retry": can_retry,
            }
        )
    return items
