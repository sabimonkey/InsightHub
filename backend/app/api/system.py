from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services.maintenance.recovery import recover_stale_jobs
from app.services.maintenance.system import readiness, system_status
from app.version import APP_VERSION

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "insighthub-api", "version": APP_VERSION}


@router.get("/ready")
def ready(session: Session = Depends(get_db)) -> dict:
    return readiness(session)


@router.get("/api/system")
def status(session: Session = Depends(get_db)) -> dict:
    return system_status(session)


@router.post("/api/system/recover")
def recover(session: Session = Depends(get_db)) -> dict:
    return recover_stale_jobs(session)
