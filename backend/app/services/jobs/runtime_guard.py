"""Guard async RQ workflows when no worker is consuming the queue."""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.services.maintenance.system import worker_detected


class WorkerNotAvailableError(Exception):
    def __init__(self, message: str = "后台任务 Worker 未运行，任务无法执行。") -> None:
        self.code = "WORKER_NOT_CONSUMING"
        self.message = message
        super().__init__(message)


def ensure_async_worker(*, settings: Settings | None = None, inline: bool) -> None:
    settings = settings or get_settings()
    if inline:
        return
    if not worker_detected(settings):
        raise WorkerNotAvailableError(
            "后台 RQ Worker 未运行。请先执行 scripts\\manage.ps1 start，或检查 Redis 连接。"
        )
