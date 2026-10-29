from collections.abc import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.jobs.analysis import enqueue_analysis
from app.jobs.extraction import enqueue_extraction
from app.jobs.discovery import build_search_provider, enqueue_discovery
from app.services.analysis.service import AnalysisService
from app.services.organization.service import OrganizationService
from app.services.discovery.service import DiscoveryService
from app.services.extraction.factory import build_extraction_service
from app.services.extraction.service import ExtractionService
from app.services.ingestion.service import IngestionService


def get_ingestion_service(db: Session = Depends(get_db)) -> Generator[IngestionService, None, None]:
    settings = get_settings()
    yield IngestionService(
        session=db,
        raw_root=settings.raw_storage_path(),
        max_upload_size_bytes=settings.max_upload_size_bytes,
    )


def get_extraction_service(db: Session = Depends(get_db)) -> Generator:
    settings = get_settings()
    yield build_extraction_service(db, settings, enqueue=enqueue_extraction)


def get_discovery_service(
    db: Session = Depends(get_db),
    ingestion: IngestionService = Depends(get_ingestion_service),
    extraction: ExtractionService = Depends(get_extraction_service),
) -> Generator[DiscoveryService, None, None]:
    settings = get_settings()
    yield DiscoveryService(
        db,
        ingestion,
        inline=settings.discovery_inline,
        search=build_search_provider(settings),
        enqueue=enqueue_discovery,
        extraction=extraction,
        timeout=settings.web_fetch_timeout_seconds,
        max_bytes=settings.web_fetch_max_bytes,
        max_redirects=settings.web_fetch_max_redirects,
    )


def get_analysis_service(db: Session = Depends(get_db)) -> Generator[AnalysisService, None, None]:
    settings = get_settings()
    yield AnalysisService(db, inline=settings.analysis_inline, settings=settings, enqueue=enqueue_analysis)


def get_organization_service(db: Session = Depends(get_db)) -> Generator[OrganizationService, None, None]:
    settings = get_settings()
    yield OrganizationService(db, threshold=settings.category_assignment_threshold)
