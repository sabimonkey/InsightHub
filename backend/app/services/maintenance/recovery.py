from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.logging import log_event
from app.models.analysis import AnalysisRun
from app.models.discovery import SourceDiscoveryRun
from app.models.extraction import ExtractionRun
from app.models.retrieval import AskTurn, IndexingRun
from app.models.cover import CoverGenerationRun
from app.models.synthesis import Brief, TopicSynthesis

COVER_ACTIVE = {"QUEUED", "GENERATING", "DECODING", "VALIDATING", "SAVING"}


def recover_stale_jobs(session: Session, settings: Settings | None = None, *, now: datetime | None = None) -> dict:
    settings = settings or get_settings()
    moment = now or datetime.now(timezone.utc)
    cutoff = moment - timedelta(seconds=settings.job_stale_after_seconds)
    recovered = []
    targets = (
        (ExtractionRun, "extraction", ExtractionRun.updated_at),
        (AnalysisRun, "analysis", AnalysisRun.started_at),
        (SourceDiscoveryRun, "discovery", SourceDiscoveryRun.started_at),
        (IndexingRun, "indexing", IndexingRun.started_at),
        (AskTurn, "ask", AskTurn.created_at),
        (Brief, "brief", Brief.created_at),
        (TopicSynthesis, "topic_synthesis", TopicSynthesis.created_at),
    )
    pending_targets = (
        (ExtractionRun, "extraction", ExtractionRun.created_at),
        (AnalysisRun, "analysis", AnalysisRun.created_at),
        (Brief, "brief", Brief.created_at),
        (TopicSynthesis, "topic_synthesis", TopicSynthesis.created_at),
    )
    for model, job_type, stamp in pending_targets:
        rows = list(session.scalars(select(model).where(model.status == "PENDING")))
        for row in rows:
            job_started_at = (getattr(row, "filters_json", None) or {}).get("worker_started_at")
            try:
                job_started_at = datetime.fromisoformat(job_started_at) if job_started_at else None
            except (TypeError, ValueError):
                job_started_at = None
            started = job_started_at or getattr(row, stamp.key, None) or getattr(row, "created_at", None)
            if started is not None and started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if started is None or started >= cutoff:
                continue
            if model is AnalysisRun:
                changed = session.execute(
                    update(AnalysisRun)
                    .where(AnalysisRun.id == row.id, AnalysisRun.status == "PENDING")
                    .values(status="FAILED", error_code="WORKER_NOT_CONSUMING", error_message="后台任务长时间未开始，请确认 Worker 已启动后重试。")
                    .returning(AnalysisRun.id)
                    .execution_options(synchronize_session=False)
                ).scalar_one_or_none()
                if changed is None:
                    continue
                session.expire(row)
                recovered.append({"job_type": job_type, "id": str(row.id), "reason": "stale_pending"})
                log_event("job_recovered", run_id=str(row.id), job_type=job_type, message="WORKER_NOT_CONSUMING")
                continue
            row.status = "FAILED"
            row.error_code = "WORKER_NOT_CONSUMING"
            row.error_message = "后台任务长时间未开始，请确认 Worker 已启动后重试。"
            if hasattr(row, "completed_at"):
                row.completed_at = moment
            recovered.append({"job_type": job_type, "id": str(row.id), "reason": "stale_pending"})
            log_event("job_recovered", run_id=str(row.id), job_type=job_type, message="WORKER_NOT_CONSUMING")
    for model, job_type, stamp in targets:
        rows = list(session.scalars(select(model).where(model.status == "RUNNING")))
        for row in rows:
            job_started_at = (getattr(row, "filters_json", None) or {}).get("worker_started_at")
            try:
                job_started_at = datetime.fromisoformat(job_started_at) if job_started_at else None
            except (TypeError, ValueError):
                job_started_at = None
            started = job_started_at or getattr(row, stamp.key, None) or getattr(row, "created_at", None)
            if started is not None and started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if started is None or started >= cutoff:
                continue
            if model is AnalysisRun:
                changed = session.execute(
                    update(AnalysisRun)
                    .where(AnalysisRun.id == row.id, AnalysisRun.status == "RUNNING")
                    .values(status="FAILED", error_code="WORKER_INTERRUPTED", error_message="后台任务中断，可以重试。", completed_at=moment)
                    .returning(AnalysisRun.id)
                    .execution_options(synchronize_session=False)
                ).scalar_one_or_none()
                if changed is None:
                    continue
                session.expire(row)
                recovered.append({"job_type": job_type, "id": str(row.id)})
                log_event("job_recovered", run_id=str(row.id), job_type=job_type, message="WORKER_INTERRUPTED")
                continue
            row.status = "FAILED"
            row.error_code = "WORKER_INTERRUPTED"
            row.error_message = "后台任务中断，可以重试。"
            if hasattr(row, "completed_at"):
                row.completed_at = moment
            recovered.append({"job_type": job_type, "id": str(row.id)})
            log_event("job_recovered", run_id=str(row.id), job_type=job_type, message="WORKER_INTERRUPTED")
    cover_rows = list(session.scalars(select(CoverGenerationRun).where(CoverGenerationRun.status.in_(COVER_ACTIVE))))
    for row in cover_rows:
        stamp = row.updated_at or row.created_at
        if stamp is not None and stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        if stamp is None or stamp >= cutoff:
            continue
        was_queued = row.stage == "QUEUED" or row.status == "QUEUED"
        row.status = "FAILED"
        row.stage = "FAILED"
        if was_queued:
            row.error_code = "WORKER_NOT_CONSUMING"
            row.error_message = "配图任务长时间未开始，请确认 Worker 已启动后重试。"
            reason = "stale_cover_queued"
        else:
            row.error_code = "WORKER_INTERRUPTED"
            row.error_message = "配图任务中断，可以重新生成。"
            reason = "stale_cover_active"
        row.updated_at = moment
        recovered.append({"job_type": "cover_generation", "id": str(row.id), "reason": reason})
        log_event("job_recovered", run_id=str(row.id), job_type="cover_generation", message=row.error_code)
    session.commit()
    return {"recovered": recovered, "count": len(recovered)}
