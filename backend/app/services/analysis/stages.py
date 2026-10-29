"""Analysis progress stages for UX (stored in AnalysisRun.metadata_json)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.analysis import AnalysisRun

STAGE_QUEUED = "QUEUED"
STAGE_PREPARING = "PREPARING"
STAGE_CALLING_MODEL = "CALLING_MODEL"
STAGE_VALIDATING = "VALIDATING"
STAGE_SAVING = "SAVING"
STAGE_SUCCEEDED = "SUCCEEDED"
STAGE_PARTIAL = "PARTIAL"
STAGE_FAILED = "FAILED"

STAGE_LABELS = {
    STAGE_QUEUED: "已提交，等待后台任务",
    STAGE_PREPARING: "正在准备资料",
    STAGE_CALLING_MODEL: "正在使用 AI 分析资料",
    STAGE_VALIDATING: "正在核对摘要与来源依据",
    STAGE_SAVING: "正在生成学习笔记",
    STAGE_SUCCEEDED: "分析完成",
    STAGE_PARTIAL: "部分完成",
    STAGE_FAILED: "分析失败",
}

ORDERED_PROGRESS = (
    STAGE_QUEUED,
    STAGE_PREPARING,
    STAGE_CALLING_MODEL,
    STAGE_VALIDATING,
    STAGE_SAVING,
)


def stage_label(stage: str | None) -> str:
    if not stage:
        return ""
    return STAGE_LABELS.get(stage, stage)


def default_stage_for_status(status: str) -> str:
    if status == "PENDING":
        return STAGE_QUEUED
    if status == "RUNNING":
        return STAGE_PREPARING
    if status == "PARTIAL":
        return STAGE_PARTIAL
    if status == "SUCCEEDED":
        return STAGE_SUCCEEDED
    if status == "FAILED":
        return STAGE_FAILED
    return STAGE_QUEUED


def read_stage(run: AnalysisRun | None) -> str | None:
    if run is None:
        return None
    meta = run.metadata_json or {}
    stage = meta.get("stage") if isinstance(meta, dict) else None
    if isinstance(stage, str) and stage:
        return stage
    return default_stage_for_status(run.status)


def set_analysis_stage(session: Session, run: AnalysisRun, stage: str) -> bool:
    """Persist progress only while the run is active, without committing unrelated work."""
    try:
        meta = dict(run.metadata_json or {})
        if meta.get("stage") == stage:
            return run.status in {"PENDING", "RUNNING"}
        meta["stage"] = stage
        meta["stage_updated_at"] = datetime.now(timezone.utc).isoformat()
        changed = session.execute(
            update(AnalysisRun)
            .where(AnalysisRun.id == run.id, AnalysisRun.status.in_(("PENDING", "RUNNING")))
            .values(metadata_json=meta)
            .returning(AnalysisRun.id)
            .execution_options(synchronize_session=False)
        ).scalar_one_or_none()
        if changed is None:
            session.rollback()
            session.refresh(run)
            return False
        session.commit()
        session.refresh(run)
        return True
    except Exception:
        session.rollback()
        try:
            session.refresh(run)
        except Exception:
            pass
        return False
