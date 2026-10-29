"""RQ jobs for source analysis."""

import uuid

from redis import Redis
from rq import Queue

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.models.analysis import AnalysisRun
from app.services.analysis.service import AnalysisService


def execute_analysis_job(run_id: str) -> str:
    settings = get_settings()
    session = get_sessionmaker()()
    try:
        run = session.get(AnalysisRun, uuid.UUID(run_id))
        if run is None:
            raise LookupError("ANALYSIS_RUN_NOT_FOUND")
        # AnalysisService acquires a slot for each outbound call. Holding another
        # slot for the job would deadlock two ZAI workers against its limit of two.
        service = AnalysisService(session, inline=True, settings=settings)
        service.execute(uuid.UUID(run_id))
        return run_id
    finally:
        session.close()


def enqueue_analysis(run_id: str) -> str:
    settings = get_settings()
    queue = Queue("insighthub", connection=Redis.from_url(settings.redis_url))
    job = queue.enqueue(
        execute_analysis_job,
        run_id,
        job_id=run_id,
        job_timeout=settings.analysis_job_timeout_seconds,
    )
    return job.id
