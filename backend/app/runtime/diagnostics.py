"""Read-only runtime diagnostics (no migrations, no LLM calls)."""

from __future__ import annotations

import json
import os
import shutil
import socket
import urllib.error
import urllib.request
from pathlib import Path

from app.core.config import PROJECT_ROOT, get_settings
from app.runtime.classification import HealthState, SERVICE_TIERS, overall_state
from app.runtime.redaction import env_config_state
from app.services.maintenance.backup import _known_revisions, schema_revision
from app.services.maintenance.system import worker_detected

DEFAULT_PORTS = {
    "backend": 8090,
    "frontend": 5174,
    "bge_m3": 8011,
    "postgresql": 5434,
    "redis": 6380,
    "lm_studio": 1234,
}


def tcp_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_json(url: str, timeout: float = 3.0) -> tuple[int | None, dict | None, str | None]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(body) if body else {}, None
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
            payload = json.loads(body) if body else {}
        except Exception:
            payload = None
        return exc.code, payload, str(exc)
    except Exception as exc:
        return None, None, str(exc)


def check_backend() -> dict:
    status, payload, err = http_json("http://127.0.0.1:8090/health")
    if status == 200 and payload and payload.get("status") == "ok":
        return {"state": HealthState.READY.value, "detail": "GET /health ok"}
    return {"state": HealthState.STOPPED.value if not tcp_open("127.0.0.1", 8090) else HealthState.FAILED.value, "detail": err or "backend unavailable"}


def check_backend_ready() -> dict:
    status, payload, err = http_json("http://127.0.0.1:8090/ready")
    if status == 200 and payload and payload.get("ready"):
        return {"state": HealthState.READY.value, "detail": "GET /ready ok", "checks": payload.get("checks")}
    return {"state": HealthState.FAILED.value, "detail": err or payload}


def check_bge() -> dict:
    status, payload, err = http_json("http://127.0.0.1:8011/health", timeout=5.0)
    if status == 200 and payload and payload.get("status") == "ok":
        model = payload.get("model")
        dims = payload.get("dimensions")
        return {"state": HealthState.READY.value, "detail": f"model={model} dimensions={dims}"}
    if not tcp_open("127.0.0.1", 8011):
        return {"state": HealthState.STOPPED.value, "detail": "8011 not listening"}
    return {"state": HealthState.FAILED.value, "detail": err or "bge health failed"}


def check_worker() -> dict:
    try:
        ok = worker_detected(get_settings())
    except Exception as exc:
        return {"state": HealthState.FAILED.value, "detail": str(exc)[:200]}
    if ok:
        return {"state": HealthState.READY.value, "detail": "RQ worker registry"}
    return {"state": HealthState.STOPPED.value, "detail": "no active RQ worker"}


def check_chromium() -> dict:
    try:
        from app.services.extraction.browser_renderer import playwright_runtime_available

        if playwright_runtime_available():
            return {"state": HealthState.READY.value, "detail": "Playwright Chromium launch ok"}
        return {"state": HealthState.DEGRADED.value, "detail": "WEB_BROWSER_FALLBACK_DEGRADED"}
    except Exception as exc:
        return {"state": HealthState.DEGRADED.value, "detail": str(exc)[:120]}


def check_postgres_redis() -> dict[str, dict]:
    pg = HealthState.READY.value if tcp_open("127.0.0.1", 5434) else HealthState.STOPPED.value
    rd = HealthState.READY.value if tcp_open("127.0.0.1", 6380) else HealthState.STOPPED.value
    return {
        "postgresql": {"state": pg, "detail": "127.0.0.1:5434"},
        "redis": {"state": rd, "detail": "127.0.0.1:6380"},
    }


def check_frontend() -> dict:
    try:
        with urllib.request.urlopen("http://127.0.0.1:5174/", timeout=2.0) as response:
            if response.status in {200, 304}:
                return {"state": HealthState.READY.value, "detail": "Vite HTTP"}
    except Exception as exc:
        if not tcp_open("127.0.0.1", 5174):
            return {"state": HealthState.STOPPED.value, "detail": "5174 not listening"}
        return {"state": HealthState.STARTING.value, "detail": str(exc)[:120]}
    if not tcp_open("127.0.0.1", 5174):
        return {"state": HealthState.STOPPED.value, "detail": "5174 not listening"}
    return {"state": HealthState.STARTING.value, "detail": "frontend starting"}


def provider_states() -> dict[str, dict]:
    settings = get_settings()
    return {
        "deepseek": {
            "state": env_config_state("DEEPSEEK_API_KEY", settings.deepseek_api_key or None),
            "detail": "route config only; not probed online",
        },
        "siliconflow": {
            "state": env_config_state("SILICONFLOW_API_KEY", settings.siliconflow_api_key or None),
            "detail": "route config only; not probed online",
        },
        "lm_studio": {
            "state": HealthState.OPTIONAL_DISABLED.value if not tcp_open("127.0.0.1", 1234) else HealthState.READY.value,
            "detail": "optional local LLM",
        },
    }


def alembic_readonly(session) -> dict:
    revision = schema_revision(session)
    known = _known_revisions()
    ok = revision in known if revision else False
    return {
        "revision": revision,
        "state": HealthState.READY.value if ok else HealthState.FAILED.value,
        "detail": "DATABASE_SCHEMA_MISMATCH" if not ok else "schema compatible",
    }


def collect_status(session=None) -> dict:
    infra = check_postgres_redis()
    services = {
        **infra,
        "backend": check_backend(),
        "backend_ready": check_backend_ready(),
        "frontend": check_frontend(),
        "rq_worker": check_worker(),
        "bge_m3": check_bge(),
        "chromium": check_chromium(),
    }
    providers = provider_states()
    states = {k: services[k]["state"] for k in SERVICE_TIERS if k in services}
    result = {
        "services": services,
        "providers": providers,
        "tiers": {k: SERVICE_TIERS[k].value for k in SERVICE_TIERS},
        "overall": overall_state(states),
        "web_url": "http://127.0.0.1:5174",
        "project_root": str(PROJECT_ROOT),
    }
    if session is not None:
        result["alembic"] = alembic_readonly(session)
    return result


def doctor_checks(project_root: Path | None = None) -> dict:
    root = project_root or PROJECT_ROOT
    python_candidates = [
        Path(os.environ["INSIGHTHUB_PYTHON"]) if os.environ.get("INSIGHTHUB_PYTHON") else None,
        root / ".venv" / "Scripts" / "python.exe",
        Path(shutil.which("python")) if shutil.which("python") else None,
    ]
    python = next((candidate for candidate in python_candidates if candidate and candidate.is_file()), None)
    bge_python_value = os.environ.get("BGE_M3_PYTHON")
    bge_python = Path(bge_python_value) if bge_python_value else None
    checks = {
        "project_root": {"ok": root.is_dir(), "path": str(root)},
        "python": {"ok": python is not None, "path": str(python) if python else None},
        "bge_python": {
            "ok": bge_python is None or bge_python.is_file(),
            "optional": True,
            "configured": bge_python is not None,
            "path": str(bge_python) if bge_python else None,
        },
        "env_file": {"ok": (root / ".env").is_file(), "path": str(root / ".env")},
        "frontend_node_modules": {"ok": (root / "frontend" / "node_modules").is_dir()},
        "compose_file": {"ok": (root / "docker-compose.yml").is_file()},
        "logs_writable": {"ok": _writable(root / "logs" / "runtime")},
    }
    checks["status"] = collect_status()
    return checks


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False
