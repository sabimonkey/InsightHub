"""RQ jobs for source discovery."""

import uuid

from redis import Redis
from rq import Queue

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.jobs.extraction import enqueue_extraction
from app.services.discovery.search import ConfigurableSearchProvider, DisabledSearchProvider, DuckDuckGoHtmlProvider
from app.services.discovery.service import DiscoveryService
from app.services.extraction.factory import build_extraction_service
from app.services.ingestion.service import IngestionService


def build_search_provider(settings=None):
    settings = settings or get_settings()
    name = (settings.search_provider or "duckduckgo").lower()
    if name == "disabled":
        return DisabledSearchProvider()
    if name == "http":
        return ConfigurableSearchProvider(settings.search_http_endpoint, settings.search_http_api_key)
    return DuckDuckGoHtmlProvider()


def execute_discovery_job(run_id: str) -> str:
    settings = get_settings()
    session = get_sessionmaker()()
    try:
        ingestion = IngestionService(session, settings.raw_storage_path(), settings.max_upload_size_bytes)
        extraction = build_extraction_service(session, settings, inline=False, enqueue=enqueue_extraction)
        service = DiscoveryService(
            session,
            ingestion,
            inline=True,
            search=build_search_provider(settings),
            extraction=extraction,
            timeout=settings.web_fetch_timeout_seconds,
            max_bytes=settings.web_fetch_max_bytes,
            max_redirects=settings.web_fetch_max_redirects,
        )
        service.execute(uuid.UUID(run_id))
        return run_id
    finally:
        session.close()


def enqueue_discovery(run_id: str) -> None:
    settings = get_settings()
    queue = Queue("insighthub", connection=Redis.from_url(settings.redis_url))
    queue.enqueue(execute_discovery_job, run_id)
