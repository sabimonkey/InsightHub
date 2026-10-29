"""RQ jobs for cover image generation."""

import uuid

from redis import Redis
from rq import Queue

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.services.cover.service import CoverGenerationService


def execute_cover_generation_job(run_id: str) -> str:
    settings = get_settings()
    session = get_sessionmaker()()
    try:
        CoverGenerationService(session, settings=settings).execute(uuid.UUID(run_id))
        return run_id
    finally:
        session.close()


def enqueue_cover_generation(run_id: str) -> None:
    settings = get_settings()
    queue = Queue("insighthub", connection=Redis.from_url(settings.redis_url))
    queue.enqueue(execute_cover_generation_job, run_id)
