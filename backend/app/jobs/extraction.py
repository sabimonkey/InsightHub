"""RQ jobs for long-running extraction."""

import uuid

from redis import Redis
from rq import Queue

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.services.extraction.factory import build_extraction_service


def execute_extraction_job(run_id: str) -> str:
    settings = get_settings()
    session = get_sessionmaker()()
    try:
        service = build_extraction_service(session, settings, inline=True)
        service.execute(uuid.UUID(run_id))
        return run_id
    finally:
        session.close()


def enqueue_extraction(run_id: str) -> None:
    settings = get_settings()
    queue = Queue("insighthub", connection=Redis.from_url(settings.redis_url))
    queue.enqueue(execute_extraction_job, run_id)
