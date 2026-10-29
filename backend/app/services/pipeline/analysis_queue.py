"""Analysis job queue views for settings UI."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.analysis import AnalysisRun
from app.models.source_item import SourceItem
from app.services.analysis.stages import read_stage, stage_label
from app.services.system_scope import USER_SCOPE

_ACTIVE = {"PENDING", "RUNNING"}


def analysis_queue_summary(session: Session) -> dict:
    counts: dict[str, int] = {}
    for status in ("PENDING", "RUNNING", "SUCCEEDED", "PARTIAL", "FAILED"):
        counts[status] = int(
            session.scalar(
                select(func.count())
                .select_from(AnalysisRun)
                .join(SourceItem, SourceItem.id == AnalysisRun.source_item_id)
                .where(SourceItem.system_scope == USER_SCOPE, SourceItem.deleted_at.is_(None), AnalysisRun.status == status)
            )
            or 0
        )
    active = counts.get("PENDING", 0) + counts.get("RUNNING", 0)
    return {
        "active": active,
        "pending": counts.get("PENDING", 0),
        "running": counts.get("RUNNING", 0),
        "succeeded": counts.get("SUCCEEDED", 0),
        "partial": counts.get("PARTIAL", 0),
        "failed": counts.get("FAILED", 0),
    }


def list_analysis_jobs(session: Session, *, limit: int = 40) -> list[dict]:
    rows = list(
        session.scalars(
            select(AnalysisRun)
            .join(SourceItem, SourceItem.id == AnalysisRun.source_item_id)
            .where(SourceItem.system_scope == USER_SCOPE, SourceItem.deleted_at.is_(None))
            .order_by(AnalysisRun.created_at.desc())
            .limit(max(1, min(limit, 100)))
        ).all()
    )
    items: list[dict] = []
    for run in rows:
        source = session.get(SourceItem, run.source_item_id)
        stage = read_stage(run)
        terminal = run.status in {"SUCCEEDED", "PARTIAL", "FAILED"}
        can_retry = run.status == "FAILED" and not _source_has_active_run(session, run.source_item_id, exclude_run_id=run.id)
        items.append(
            {
                "run_id": str(run.id),
                "source_id": str(run.source_item_id),
                "source_title": source.display_name if source else "—",
                "status": run.status,
                "stage": stage,
                "stage_label": stage_label(stage),
                "provider_type": run.provider_type,
                "model_name": run.model_name,
                "is_simulated": run.provider_type == "FAKE" or run.model_name == "fake-model",
                "error_code": run.error_code,
                "error_message": run.error_message,
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "is_active": run.status in _ACTIVE,
                "can_retry": can_retry,
            }
        )
    return items


def _source_has_active_run(session: Session, source_id, *, exclude_run_id=None) -> bool:
    stmt = select(AnalysisRun.id).where(
        AnalysisRun.source_item_id == source_id,
        AnalysisRun.status.in_(_ACTIVE),
    )
    if exclude_run_id is not None:
        stmt = stmt.where(AnalysisRun.id != exclude_run_id)
    return session.scalar(stmt.limit(1)) is not None
