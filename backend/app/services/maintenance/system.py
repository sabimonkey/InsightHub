import ctypes
import os
import shutil
import socket
from datetime import datetime, timedelta, timezone

from redis import Redis
from rq import Worker
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT, Settings, get_settings
from app.models.analysis import Claim
from app.models.extraction import ContentChunk
from app.models.retrieval import ChunkEmbedding
from app.models.source_asset import SourceAsset
from app.models.source_item import SourceItem
from app.models.synthesis import Brief
from app.services.maintenance.backup import _known_revisions, schema_revision
from app.version import APP_VERSION


def worker_detected(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=2)
        local_host = socket.gethostname()
        for worker in Worker.all(connection=Redis.from_url(settings.redis_url)):
            if worker.hostname == local_host:
                if _local_worker_process_alive(worker.pid):
                    return True
                continue
            if worker.last_heartbeat is not None and worker.last_heartbeat >= cutoff:
                return True
        return False
    except Exception:
        return False


def _local_worker_process_alive(pid: int) -> bool:
    """RQ idle workers may not refresh last_heartbeat; verify local process liveness."""
    if os.name != "nt":
        try:
            os.kill(int(pid), 0)
            return True
        except (OSError, ValueError):
            return False

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
    kernel32.GetExitCodeProcess.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    exit_code = ctypes.c_ulong()
    try:
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) and exit_code.value == 259)
    finally:
        kernel32.CloseHandle(handle)


def system_status(session: Session, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    postgres = _postgres(session)
    redis = _redis(settings)
    revision = schema_revision(session)
    known = _known_revisions()
    schema_ok = revision in known if revision else False
    storage = settings.raw_storage_path()
    usage = shutil.disk_usage(storage if storage.exists() else PROJECT_ROOT)
    raw_files = session.scalar(select(func.count()).select_from(SourceAsset)) or 0
    raw_bytes = session.scalar(select(func.coalesce(func.sum(SourceAsset.size_bytes), 0))) or 0
    latest_backup = _latest_backup()
    return {
        "version": APP_VERSION,
        "backend": "ok",
        "postgres": postgres,
        "redis": redis,
        "worker": "running" if worker_detected(settings) else "not_detected",
        "alembic": {"revision": revision, "ok": schema_ok},
        "raw_storage": "ok" if storage.exists() else "missing",
        "disk": {
            "path": str(storage),
            "used": usage.used,
            "available": usage.free,
            "warning": usage.free < settings.disk_low_warning_bytes,
        },
        "counts": {
            "sources": session.scalar(select(func.count()).select_from(SourceItem)) or 0,
            "raw_files": raw_files,
            "raw_bytes": int(raw_bytes),
            "chunks": session.scalar(select(func.count()).select_from(ContentChunk)) or 0,
            "claims": session.scalar(select(func.count()).select_from(Claim)) or 0,
            "embeddings": session.scalar(select(func.count()).select_from(ChunkEmbedding)) or 0,
            "briefs": session.scalar(select(func.count()).select_from(Brief)) or 0,
        },
        "optional": {"llm_configured": bool(settings.llm_default_provider or settings.llm_enable_fake), "embedding_configured": settings.embedding_enable_fake or bool(settings.local_embedding_model)},
        "latest_backup": latest_backup,
        "backup_command": "scripts\\backup.ps1",
    }


def _postgres(session: Session) -> str:
    try:
        session.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "unavailable"


def _redis(settings: Settings) -> str:
    try:
        Redis.from_url(settings.redis_url).ping()
        return "ok"
    except Exception:
        return "unavailable"


def _latest_backup() -> str | None:
    root = PROJECT_ROOT / "data" / "backup"
    if not root.exists():
        return None
    candidates = [path for path in root.iterdir() if path.is_dir() and (path / "manifest.json").is_file()]
    if not candidates:
        return None
    return str(max(candidates, key=lambda item: item.stat().st_mtime))


def readiness(session: Session, settings: Settings | None = None) -> dict:
    status = system_status(session, settings)
    checks = {"postgres": status["postgres"] == "ok", "redis": status["redis"] == "ok", "schema": status["alembic"]["ok"]}
    return {"ready": all(checks.values()), "checks": checks, "version": APP_VERSION, "error": None if all(checks.values()) else "DATABASE_MIGRATION_REQUIRED" if not checks["schema"] else "NOT_READY"}
