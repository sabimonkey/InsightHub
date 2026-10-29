"""Managed process manifest (stored under data/run, not committed)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MANIFEST_VERSION = 1


@dataclass
class ManagedProcess:
    service: str
    pid: int
    started_at: str
    command_identity: str
    project_root: str
    port: int | None = None
    owned_by_launcher: bool = True
    creation_time: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeManifest:
    version: int
    project_root: str
    services: dict[str, ManagedProcess] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "project_root": self.project_root,
            "services": {name: proc.to_dict() for name, proc in self.services.items()},
        }


def manifest_path(project_root: Path) -> Path:
    return project_root / "data" / "run" / "managed_processes.json"


def load_manifest(path: Path) -> RuntimeManifest | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    services: dict[str, ManagedProcess] = {}
    for name, item in (raw.get("services") or {}).items():
        if not isinstance(item, dict):
            continue
        services[name] = ManagedProcess(
            service=str(item.get("service") or name),
            pid=int(item["pid"]),
            started_at=str(item.get("started_at") or ""),
            command_identity=str(item.get("command_identity") or ""),
            project_root=str(item.get("project_root") or raw.get("project_root") or ""),
            port=item.get("port"),
            owned_by_launcher=bool(item.get("owned_by_launcher", True)),
            creation_time=item.get("creation_time"),
        )
    return RuntimeManifest(
        version=int(raw.get("version") or MANIFEST_VERSION),
        project_root=str(raw.get("project_root") or ""),
        services=services,
    )


def save_manifest(path: Path, manifest: RuntimeManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def upsert_service(manifest: RuntimeManifest, proc: ManagedProcess) -> None:
    manifest.services[proc.service] = proc


def remove_service(manifest: RuntimeManifest, service: str) -> None:
    manifest.services.pop(service, None)


def verify_process_identity(
    *,
    pid: int,
    command_identity: str,
    project_root: str,
    creation_time: str | None,
    process_creation_iso: str | None,
    command_line: str | None,
) -> bool:
    if not command_line:
        return False
    if command_identity not in command_line:
        return False
    if creation_time and process_creation_iso and creation_time != process_creation_iso:
        return False
    return True


def is_stale_manifest_entry(proc: ManagedProcess, alive: bool, identity_ok: bool) -> bool:
    if not alive:
        return True
    return not identity_ok


def new_managed_process(
    service: str,
    pid: int,
    command_identity: str,
    project_root: str,
    port: int | None = None,
    creation_time: str | None = None,
) -> ManagedProcess:
    return ManagedProcess(
        service=service,
        pid=pid,
        started_at=datetime.now(timezone.utc).isoformat(),
        command_identity=command_identity,
        project_root=project_root,
        port=port,
        owned_by_launcher=True,
        creation_time=creation_time,
    )
