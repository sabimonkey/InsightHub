import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT, Settings, get_settings
from app.version import APP_VERSION

BACKUP_VERSION = "1"
SECRET_NAMES = (
    "DEEPSEEK_API_KEY",
    "SILICONFLOW_API_KEY",
    "GENERIC_LLM_API_KEY",
    "GENERIC_EMBEDDING_API_KEY",
    "SILICONFLOW_EMBEDDING_API_KEY",
    "POSTGRES_PASSWORD",
)


class BackupError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_tree(source: Path, destination: Path) -> tuple[int, int]:
    count = 0
    total = 0
    if not source.exists():
        return 0, 0
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        count += 1
        total += path.stat().st_size
    return count, total


def _known_revisions() -> set[str]:
    versions = PROJECT_ROOT / "backend" / "alembic" / "versions"
    found = set()
    if not versions.exists():
        return found
    for path in versions.glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("revision") and "=" in line:
                found.add(line.split("=", 1)[1].strip().strip("\"'"))
    return found


def schema_revision(session: Session | None) -> str | None:
    if session is None:
        return None
    try:
        return session.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    except Exception:
        return None


def git_commit() -> str | None:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)
    except OSError:
        return None
    return result.stdout.strip() or None


def _database_parts(database_url: str) -> tuple[str, str, str]:
    parsed = urlparse(database_url.replace("postgresql+psycopg", "postgresql"))
    return parsed.username or "insighthub", parsed.password or "", (parsed.path or "/insighthub").lstrip("/")


def dump_database(target: Path, settings: Settings) -> None:
    user, password, database = _database_parts(settings.database_url)
    command = [
        "docker",
        "exec",
        "-e",
        f"PGPASSWORD={password}",
        settings.backup_postgres_container,
        "pg_dump",
        "-U",
        user,
        "-d",
        database,
        "--no-owner",
        "--no-acl",
    ]
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode != 0:
        raise BackupError("DATABASE_DUMP_FAILED", "数据库导出失败。")
    target.write_bytes(result.stdout)


def create_backup(destination: Path, session: Session | None = None, settings: Settings | None = None, *, dump_runner=None, raw_root: Path | None = None, extracted_root: Path | None = None) -> Path:
    settings = settings or get_settings()
    destination = destination.resolve()
    staging = destination.with_name(destination.name + ".partial")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        dump_path = staging / "database.sql"
        if dump_runner is not None:
            dump_runner(dump_path)
        else:
            dump_database(dump_path, settings)
        raw_count, raw_bytes = _copy_tree(raw_root or settings.raw_storage_path(), staging / "raw")
        extracted_count, _ = _copy_tree(extracted_root or settings.extracted_storage_path(), staging / "extracted")
        included = ["database.sql"]
        if raw_count:
            included.append("raw")
        if extracted_count:
            included.append("extracted")
        checksums = {}
        for path in sorted(item for item in staging.rglob("*") if item.is_file()):
            checksums[path.relative_to(staging).as_posix()] = _sha256(path)
        manifest = {
            "backup_version": BACKUP_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "app_version": APP_VERSION,
            "git_commit": git_commit(),
            "database_schema_revision": schema_revision(session),
            "database_dump": "database.sql",
            "raw_asset_count": raw_count,
            "raw_bytes": raw_bytes,
            "included_directories": included,
            "checksums": checksums,
            "required_secret_names": [name for name in SECRET_NAMES],
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (staging / "SHA256SUMS").write_text(_sha256(staging / "manifest.json") + "  manifest.json\n", encoding="utf-8")
        verify_backup(staging)
        if destination.exists():
            raise BackupError("BACKUP_EXISTS", "目标备份已存在。")
        os.replace(staging, destination)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination


def verify_backup(path: Path) -> dict:
    manifest_path = path / "manifest.json"
    sums = path / "SHA256SUMS"
    if not manifest_path.is_file() or not sums.is_file():
        raise BackupError("BACKUP_INTEGRITY_FAILED", "备份清单缺失。")
    expected, _, name = sums.read_text(encoding="utf-8").partition("  ")
    if name.strip() != "manifest.json" or expected != _sha256(manifest_path):
        raise BackupError("BACKUP_INTEGRITY_FAILED", "备份清单校验失败。")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checksums = manifest.get("checksums") or {}
    for relative, expected in checksums.items():
        target = path / relative
        if not target.is_file() or _sha256(target) != expected:
            raise BackupError("BACKUP_INTEGRITY_FAILED", "备份校验失败。")
    return manifest


def assert_compatible(manifest: dict) -> None:
    if manifest.get("backup_version") != BACKUP_VERSION:
        raise BackupError("BACKUP_INCOMPATIBLE", "备份格式不受当前版本支持。")
    revision = manifest.get("database_schema_revision")
    if revision and revision not in _known_revisions():
        raise BackupError("BACKUP_INCOMPATIBLE", "备份的数据库结构比当前应用更新。")


def restore_backup(path: Path, settings: Settings | None = None, *, confirm: bool = False, restore_runner=None, raw_root: Path | None = None, extracted_root: Path | None = None) -> dict:
    if not confirm:
        raise BackupError("RESTORE_CONFIRMATION_REQUIRED", "恢复必须显式确认。")
    settings = settings or get_settings()
    manifest = verify_backup(path)
    assert_compatible(manifest)
    if restore_runner is not None:
        restore_runner(path / manifest["database_dump"])
    else:
        _restore_database(path / manifest["database_dump"], settings)
    if (path / "raw").exists():
        _copy_tree(path / "raw", raw_root or settings.raw_storage_path())
    if (path / "extracted").exists():
        _copy_tree(path / "extracted", extracted_root or settings.extracted_storage_path())
    return {"restored": str(path), "schema_revision": manifest.get("database_schema_revision")}


def _restore_database(dump: Path, settings: Settings) -> None:
    user, password, database = _database_parts(settings.database_url)
    command = ["docker", "exec", "-i", "-e", f"PGPASSWORD={password}", settings.backup_postgres_container, "psql", "-U", user, "-d", database]
    result = subprocess.run(command, input=dump.read_bytes(), capture_output=True, check=False)
    if result.returncode != 0:
        raise BackupError("DATABASE_RESTORE_FAILED", "数据库恢复失败。")
