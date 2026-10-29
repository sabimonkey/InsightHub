import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.analysis import router as analysis_router
from app.api.cover import router as cover_router
from app.api.discovery import router as discovery_router
from app.api.extraction import router as extraction_router
from app.api.inbox import router as inbox_router
from app.api.ingest import router as ingest_router
from app.api.organization import router as organization_router
from app.api.retrieval import router as retrieval_router
from app.api.sources import router as sources_router
from app.api.synthesis import router as synthesis_router
from app.api.system import router as health_router
from app.core.logging import configure_logging, log_event
from app.db.session import get_sessionmaker
from app.services.analysis.service import AnalysisError
from app.services.discovery.service import DiscoveryError
from app.services.ingestion.errors import IngestionError
from app.services.maintenance.recovery import recover_stale_jobs
from app.services.organization.service import OrganizationError
from app.version import APP_VERSION


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    try:
        session = get_sessionmaker()()
        try:
            recover_stale_jobs(session)
            from app.core.config import get_settings
            from app.services.cover.auto import scan_and_enqueue_auto_covers
            from app.services.cover.settings_prefs import load_cover_prefs

            settings = get_settings()
            prefs = load_cover_prefs(session, settings)
            # E2E/test servers share the application database for isolated
            # AUTOMATION_TEST records. Never run a global USER cover scan from
            # that server, even if the persisted production toggle is enabled.
            if (
                prefs.auto_enabled
                and settings.cover_auto_startup_scan_enabled
                and settings.insighthub_system_scope != "AUTOMATION_TEST"
            ):
                scan_and_enqueue_auto_covers(session, settings=settings, limit=30)
        finally:
            session.close()
    except Exception as exc:
        log_event("startup_recovery_skipped", level=logging.WARNING, message=type(exc).__name__)
    yield


app = FastAPI(title="InsightHub API", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5174", "http://localhost:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(ingest_router)
app.include_router(inbox_router)
app.include_router(sources_router)
app.include_router(extraction_router)
app.include_router(discovery_router)
app.include_router(analysis_router)
app.include_router(cover_router)
app.include_router(organization_router)
app.include_router(retrieval_router)
app.include_router(synthesis_router)


@app.exception_handler(IngestionError)
def handle_ingestion_error(_request: Request, exc: IngestionError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"code": exc.code, "message": exc.message})


@app.exception_handler(AnalysisError)
def handle_analysis_error(_request: Request, exc: AnalysisError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"code": exc.code, "message": exc.message})


@app.exception_handler(OrganizationError)
def handle_organization_error(_request: Request, exc: OrganizationError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"code": exc.code, "message": exc.message})


@app.exception_handler(DiscoveryError)
def handle_discovery_error(_request: Request, exc: DiscoveryError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"code": exc.code, "message": exc.message})


@app.exception_handler(Exception)
async def unhandled_exception(_request: Request, exc: Exception) -> JSONResponse:
    error_id = f"ERR-{uuid.uuid4().hex[:8]}"
    log_event("unhandled_error", level=logging.ERROR, message=f"{error_id} {type(exc).__name__}")
    return JSONResponse(status_code=500, content={"error_id": error_id, "message": "请求失败。"})
