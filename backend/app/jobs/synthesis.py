import uuid
import logging
from datetime import datetime, timezone

from redis import Redis
from rq import Queue
from rq.timeouts import JobTimeoutException
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.services.synthesis.service import SynthesisService
from app.models.synthesis import Brief, TopicSynthesis

logger = logging.getLogger(__name__)


def execute_brief(brief_id: str) -> str:
    session = get_sessionmaker()()
    try:
        SynthesisService(session, get_settings(), inline=True).execute_brief(uuid.UUID(brief_id))
        return brief_id
    finally:
        session.close()


def synthesis_job_failed(job, _connection, exc_type, _exc_value, _traceback) -> None:
    """Persist RQ failures/timeouts without copying exception payloads into user-visible storage."""
    args = list(getattr(job, "args", ()) or ())
    if not args:
        return
    try:
        item_id = uuid.UUID(str(args[0]))
    except (TypeError, ValueError):
        return
    try:
        session = get_sessionmaker()()
        try:
            if getattr(job, "func_name", "").endswith("execute_topic_synthesis"):
                row = session.scalar(select(TopicSynthesis).where(TopicSynthesis.id == item_id).with_for_update())
            else:
                row = session.scalar(select(Brief).where(Brief.id == item_id).with_for_update())
            if row is None or row.status not in {"PENDING", "RUNNING"}:
                return
            is_timeout = isinstance(exc_type, type) and issubclass(exc_type, JobTimeoutException)
            row.status = "FAILED"
            row.error_code = "JOB_TIMEOUT" if is_timeout else "JOB_FAILED"
            row.error_message = "笔记生成超过后台任务时间上限。" if is_timeout else "后台任务异常终止，可重新生成。"
            row.completed_at = datetime.now(timezone.utc)
            session.commit()
        finally:
            session.close()
    except Exception as exc:
        logger.error("could not persist synthesis job failure (%s)", type(exc).__name__)


def execute_topic_synthesis(synthesis_id: str) -> str:
    session = get_sessionmaker()()
    try:
        SynthesisService(session, get_settings(), inline=True).execute_topic(uuid.UUID(synthesis_id))
        return synthesis_id
    finally:
        session.close()


def enqueue_synthesis(kind: str, item_id: str) -> None:
    settings = get_settings()
    queue = Queue("insighthub", connection=Redis.from_url(settings.redis_url))
    timeout = max(int(settings.llm_timeout_seconds) * 3, 600)
    if kind == "topic":
        queue.enqueue(execute_topic_synthesis, item_id, job_timeout=timeout, job_id=item_id, on_failure=synthesis_job_failed, result_ttl=86400, failure_ttl=604800)
    else:
        queue.enqueue(execute_brief, item_id, job_timeout=timeout, job_id=item_id, on_failure=synthesis_job_failed, result_ttl=86400, failure_ttl=604800)
