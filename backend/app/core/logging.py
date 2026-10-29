import json
import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.config import PROJECT_ROOT

SECRET_PATTERNS = re.compile(r"(?i)(api[_-]?key|authorization|password|secret)\s*[:=]\s*\S+(?:\s+\S+)?|bearer\s+\S+|sk-[A-Za-z0-9]+")


def redact(value: object) -> str:
    return SECRET_PATTERNS.sub("[redacted]", str(value))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "event": getattr(record, "event", record.getMessage()),
            "run_id": getattr(record, "run_id", None),
            "source_id": getattr(record, "source_id", None),
            "job_type": getattr(record, "job_type", None),
            "message": redact(record.getMessage()),
        }
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    root = logging.getLogger("insighthub")
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    directory = PROJECT_ROOT / "data" / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(directory / "insighthub.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)


def log_event(event: str, *, level: int = logging.INFO, run_id: str | None = None, source_id: str | None = None, job_type: str | None = None, message: str = "") -> None:
    configure_logging()
    logging.getLogger("insighthub").log(level, message or event, extra={"event": event, "run_id": run_id, "source_id": source_id, "job_type": job_type})


def log_directory() -> Path:
    return PROJECT_ROOT / "data" / "logs"
