import uuid
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session
from redis import Redis
from rq.job import Job
from rq.exceptions import NoSuchJobError

from app.core.config import get_settings
from app.db.session import get_db
from app.jobs.synthesis import enqueue_synthesis
from app.models.synthesis import Brief, BriefCitation, BriefSource, TopicSynthesis, TopicSynthesisCitation
from app.services.synthesis.exporting import markdown_name, write_docx, write_markdown, write_pdf
from app.services.jobs.runtime_guard import WorkerNotAvailableError, ensure_async_worker
from app.services.synthesis.service import SynthesisService

router = APIRouter(prefix="/api", tags=["synthesis"])


class BriefRequest(BaseModel):
    start_date: str | None = None
    end_date: str | None = None
    date_basis: str = "COLLECTED_AT"
    detail_level: str = "STANDARD"
    category_slugs: list[str] = []
    topic_ids: list[str] = []
    provider_type: str | None = None


def _db(db: Session = Depends(get_db)) -> Session:
    return db


@router.post("/briefs/preview")
def preview_brief(body: BriefRequest, db: Session = Depends(_db)) -> dict:
    return SynthesisService(db).preview(body.model_dump())


@router.post("/briefs")
def create_brief(body: BriefRequest, db: Session = Depends(_db)) -> dict:
    settings = get_settings()
    try:
        ensure_async_worker(settings=settings, inline=settings.brief_inline)
    except WorkerNotAvailableError as exc:
        raise HTTPException(status_code=503, detail={"code": exc.code, "message": exc.message}) from exc
    brief = SynthesisService(db, settings, inline=settings.brief_inline, enqueue=enqueue_synthesis).create_brief(body.model_dump(), body.provider_type)
    return _brief(db, brief)


@router.get("/briefs")
def list_briefs(db: Session = Depends(_db)) -> dict:
    from app.services.system_scope import api_visibility_filter

    completion_rank = (Brief.status.in_(["SUCCEEDED", "PARTIAL", "NO_CONTENT"])).desc()
    rows = list(
        db.scalars(
            select(Brief)
            .where(api_visibility_filter(Brief.system_scope))
            .order_by(completion_rank, Brief.completed_at.desc().nullslast(), Brief.created_at.desc(), Brief.id.desc())
        )
    )
    for row in rows:
        _reconcile_stale_brief(db, row)
    return {"briefs": [_brief(db, row) for row in rows]}


@router.delete("/briefs")
def clear_brief_history(db: Session = Depends(_db)) -> dict:
    from app.services.system_scope import api_visibility_filter

    rows = list(db.scalars(select(Brief).where(api_visibility_filter(Brief.system_scope)).with_for_update()))
    if any(row.status in {"PENDING", "RUNNING"} for row in rows):
        raise HTTPException(status_code=409, detail={"code": "BRIEF_TASK_ACTIVE", "message": "有笔记任务仍在排队或生成，请等待终态后再清空历史。"})
    ids = [row.id for row in rows]
    if not ids:
        return {"deleted_count": 0}
    db.execute(update(Brief).where(Brief.regenerated_from_id.in_(ids)).values(regenerated_from_id=None))
    db.execute(delete(BriefCitation).where(BriefCitation.brief_id.in_(ids)))
    db.execute(delete(BriefSource).where(BriefSource.brief_id.in_(ids)))
    db.execute(delete(Brief).where(Brief.id.in_(ids)))
    db.commit()
    return {"deleted_count": len(ids)}


@router.get("/briefs/{brief_id}")
def get_brief(brief_id: uuid.UUID, db: Session = Depends(_db)) -> dict:
    from app.services.system_scope import scope_visible_for_api

    row = db.get(Brief, brief_id)
    if row is None or not scope_visible_for_api(row.system_scope):
        return {"brief": None}
    _reconcile_stale_brief(db, row)
    return _brief(db, row)


def _reconcile_stale_brief(db: Session, row: Brief) -> None:
    if row.status not in {"PENDING", "RUNNING"}:
        return
    settings = get_settings()
    started_value = (row.filters_json or {}).get("worker_started_at")
    try:
        started_at = datetime.fromisoformat(started_value) if started_value else row.created_at
    except (TypeError, ValueError):
        started_at = row.created_at
    if started_at is None:
        return
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc) - started_at).total_seconds() < settings.job_stale_after_seconds:
        return

    job_id = (row.filters_json or {}).get("rq_job_id")
    if not job_id:
        previous_status = row.status
        row.status = "FAILED"
        row.error_code = "WORKER_INTERRUPTED" if previous_status == "RUNNING" else "WORKER_NOT_CONSUMING"
        row.error_message = "后台任务超过状态恢复时限，已标记为失败；原有资料未被修改。"
        row.completed_at = datetime.now(timezone.utc)
        db.commit()
        return
    try:
        job = Job.fetch(str(job_id), connection=Redis.from_url(settings.redis_url))
        rq_status = job.get_status(refresh=True).value
    except NoSuchJobError:
        rq_status = "MISSING"
    except Exception:
        return
    if rq_status in {"queued", "started", "scheduled", "deferred"}:
        return
    previous_status = row.status
    row.status = "FAILED"
    if rq_status == "failed":
        row.error_code = "JOB_TIMEOUT" if "JobTimeoutException" in (job.exc_info or "") else "JOB_FAILED"
        row.error_message = "后台任务已终止，但没有保存可读取的学习笔记。"
    elif rq_status == "finished":
        row.error_code = "RESULT_NOT_PERSISTED"
        row.error_message = "后台任务已结束，但没有提交可读取的学习笔记。"
    elif rq_status == "stopped":
        row.error_code = "JOB_STOPPED"
        row.error_message = "后台任务已停止，未保存学习笔记。"
    else:
        row.error_code = "WORKER_INTERRUPTED" if previous_status == "RUNNING" else "WORKER_NOT_CONSUMING"
        row.error_message = "后台任务记录已过期且队列中不存在对应任务，已标记为失败。"
    row.completed_at = datetime.now(timezone.utc)
    db.commit()


@router.delete("/briefs/{brief_id}")
def delete_brief(brief_id: uuid.UUID, db: Session = Depends(_db)) -> dict:
    from app.services.system_scope import scope_visible_for_api

    row = db.scalar(select(Brief).where(Brief.id == brief_id).with_for_update())
    if row is None or not scope_visible_for_api(row.system_scope):
        return {"deleted": False, "id": str(brief_id)}
    if row.status in {"PENDING", "RUNNING"}:
        raise HTTPException(status_code=409, detail={"code": "BRIEF_TASK_ACTIVE", "message": "这条笔记仍在排队或生成，不能删除。"})
    db.execute(update(Brief).where(Brief.regenerated_from_id == row.id).values(regenerated_from_id=None))
    db.execute(delete(BriefCitation).where(BriefCitation.brief_id == row.id))
    db.execute(delete(BriefSource).where(BriefSource.brief_id == row.id))
    db.delete(row)
    db.commit()
    return {"deleted": True, "id": str(brief_id)}


@router.post("/briefs/{brief_id}/regenerate")
def regenerate_brief(brief_id: uuid.UUID, db: Session = Depends(_db)) -> dict:
    settings = get_settings()
    try:
        ensure_async_worker(settings=settings, inline=settings.brief_inline)
    except WorkerNotAvailableError as exc:
        raise HTTPException(status_code=503, detail={"code": exc.code, "message": exc.message}) from exc
    brief = SynthesisService(db, settings, inline=settings.brief_inline, enqueue=enqueue_synthesis).regenerate(brief_id)
    return _brief(db, brief)


@router.get("/briefs/{brief_id}/export")
def export_brief(brief_id: uuid.UUID, format: str = "markdown", db: Session = Depends(_db)):
    brief = db.get(Brief, brief_id)
    if brief is None:
        return {"brief": None}
    sources = _sources(db, brief)
    if format == "docx":
        payload = write_docx(brief, sources)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        name = markdown_name(brief).replace(".md", ".docx")
    elif format == "pdf":
        payload = write_pdf(brief)
        media = "application/pdf"
        name = markdown_name(brief).replace(".md", ".pdf")
    else:
        payload = write_markdown(brief)
        media = "text/markdown; charset=utf-8"
        name = markdown_name(brief)
    return Response(content=payload, media_type=media, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@router.post("/topics/{topic_id}/synthesize")
def synthesize_topic(topic_id: uuid.UUID, body: BriefRequest, db: Session = Depends(_db)) -> dict:
    settings = get_settings()
    row = SynthesisService(db, settings, inline=settings.brief_inline, enqueue=enqueue_synthesis).create_topic_synthesis(topic_id, body.provider_type, body.model_dump())
    return _topic(db, row)


@router.get("/topics/{topic_id}/syntheses")
def list_syntheses(topic_id: uuid.UUID, db: Session = Depends(_db)) -> dict:
    rows = list(db.scalars(select(TopicSynthesis).where(TopicSynthesis.topic_id == topic_id).order_by(TopicSynthesis.created_at.desc())))
    return {"syntheses": [_topic(db, row) for row in rows]}


@router.get("/topic-syntheses/{synthesis_id}")
def get_synthesis(synthesis_id: uuid.UUID, db: Session = Depends(_db)) -> dict:
    row = db.get(TopicSynthesis, synthesis_id)
    if row is None:
        return {"synthesis": None}
    return _topic(db, row)


def _brief(db: Session, row: Brief) -> dict:
    from app.services.synthesis.learning_note import project_learning_note

    citations = list(db.scalars(select(BriefCitation).where(BriefCitation.brief_id == row.id).order_by(BriefCitation.citation_number)))
    sources = list(db.scalars(select(BriefSource).where(BriefSource.brief_id == row.id)))
    learning = project_learning_note(row.structured_result_json if isinstance(row.structured_result_json, dict) else None)
    return {
        "id": row.id,
        "title": row.title,
        "status": row.status,
        "job_id": (row.filters_json or {}).get("rq_job_id"),
        "provider_type": row.provider_type,
        "model_name": row.model_name,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "total_tokens": row.total_tokens,
        "latency_ms": row.latency_ms,
        "start_date": row.start_date,
        "end_date": row.end_date,
        "date_basis": row.date_basis,
        "detail_level": row.detail_level,
        "prompt_name": row.prompt_name,
        "content_markdown": row.content_markdown,
        "selected_source_count": row.selected_source_count,
        "included_source_count": row.included_source_count,
        "excluded_source_count": row.excluded_source_count,
        "exclusion_reasons": row.exclusion_reasons_json,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "regenerated_from_id": row.regenerated_from_id,
        "filters": {key: value for key, value in (row.filters_json or {}).items() if key in {"category_slugs", "topic_ids", "scope", "requested_provider", "actual_provider", "is_local", "output_strategy"}},
        "generation_diagnostics": (row.filters_json or {}).get("generation_diagnostics"),
        "sources": [
            {
                "source_id": item.source_item_id,
                "role": item.role,
                "included": item.included,
                "exclusion_reason": item.exclusion_reason,
                "collection_count": item.collection_count,
                "citation_number": item.citation_number,
            }
            for item in sources
        ],
        "citations": [
            {
                "citation_number": item.citation_number,
                "source_item_id": item.source_item_id,
                "claim_id": item.claim_id,
                "content_chunk_id": item.content_chunk_id,
                "quote_text": item.quote_text,
            }
            for item in citations
        ],
        "source_index": _sources(db, row),
        "learning_note": learning,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


def _sources(db: Session, row: Brief) -> list[dict]:
    from app.models.source_asset import SourceAsset
    from app.models.source_item import SourceItem

    numbers = {}
    for item in db.scalars(select(BriefCitation).where(BriefCitation.brief_id == row.id)):
        numbers.setdefault(item.source_item_id, item.citation_number)
    index = []
    for source_id, number in sorted(numbers.items(), key=lambda item: item[1]):
        source = db.get(SourceItem, source_id)
        asset = db.scalar(select(SourceAsset).where(SourceAsset.source_item_id == source_id))
        index.append(
            {
                "citation_number": number,
                "source_id": source_id,
                "title": None if source is None else source.display_name,
                "source_type": None if source is None else source.source_type,
                "original_url": None if source is None else source.original_url,
                "canonical_url": None if source is None else source.canonical_url,
                "filename": None if asset is None else asset.original_filename,
            }
        )
    return index


def _topic(db: Session, row: TopicSynthesis) -> dict:
    citations = list(db.scalars(select(TopicSynthesisCitation).where(TopicSynthesisCitation.synthesis_id == row.id)))
    return {
        "id": row.id,
        "topic_id": row.topic_id,
        "status": row.status,
        "provider_type": row.provider_type,
        "model_name": row.model_name,
        "source_count": row.source_count,
        "created_at": row.created_at,
        "content_markdown": row.content_markdown,
        "error_code": row.error_code,
        "citations": [
            {
                "citation_number": item.citation_number,
                "source_item_id": item.source_item_id,
                "claim_id": item.claim_id,
                "content_chunk_id": item.content_chunk_id,
                "quote_text": item.quote_text,
            }
            for item in citations
        ],
    }
