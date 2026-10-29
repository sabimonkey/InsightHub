import json
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.logging import log_event, redact
from app.main import app
from app.models.analysis import AnalysisRun
from app.models.extraction import ExtractedDocument, ExtractionRun
from app.models.source_asset import SourceAsset
from app.models.source_item import SourceItem
from app.models.retrieval import AskSession, AskTurn
from app.models.synthesis import Brief
from app.services.llm.fallback import select_fallback
from app.services.maintenance.audit import audit_data, audit_storage
from app.services.maintenance.backup import BackupError, assert_compatible, create_backup, restore_backup, verify_backup
from app.services.maintenance.paths import resolve_under
from app.services.maintenance.portable import export_library
from app.services.maintenance.recovery import recover_stale_jobs
from app.services.maintenance.system import readiness, system_status
from app.services.synthesis.exporting import cache_export
from app.version import APP_VERSION


def test_health_ready_and_version():
    with TestClient(app) as client:
        health = client.get("/health")
        ready = client.get("/ready")
    assert health.status_code == 200
    assert health.json()["version"] == APP_VERSION
    assert ready.status_code == 200
    assert ready.json()["checks"]["postgres"] is True
    assert "schema" in ready.json()["checks"]


def test_backup_checksum_restore_and_rejection(db_session, tmp_path: Path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "aa" / "bb").mkdir(parents=True)
    asset = raw / "aa" / "bb" / "file.bin"
    asset.write_bytes(b"raw-bytes")
    destination = tmp_path / "backup"
    create_backup(destination, db_session, get_settings(), dump_runner=lambda path: path.write_text("SELECT 1;\n", encoding="utf-8"), raw_root=raw, extracted_root=tmp_path / "extracted")
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["backup_version"] == "1"
    assert "DEEPSEEK_API_KEY" in manifest["required_secret_names"]
    assert "raw" in manifest["included_directories"]
    assert manifest["checksums"]["database.sql"]
    verify_backup(destination)
    try:
        restore_backup(destination, confirm=False)
    except BackupError as exc:
        assert exc.code == "RESTORE_CONFIRMATION_REQUIRED"
    else:
        raise AssertionError("restore without confirmation")
    asset.write_bytes(b"changed")
    restored = tmp_path / "restored-raw"
    restore_backup(destination, confirm=True, restore_runner=lambda path: None, raw_root=restored, extracted_root=tmp_path / "restored-extracted")
    assert (restored / "aa" / "bb" / "file.bin").read_bytes() == b"raw-bytes"
    broken = destination / "database.sql"
    broken.write_bytes(b"broken")
    try:
        verify_backup(destination)
    except BackupError as exc:
        assert exc.code == "BACKUP_INTEGRITY_FAILED"
    else:
        raise AssertionError("corrupt backup")
    try:
        assert_compatible({"backup_version": "1", "database_schema_revision": "future-revision"})
    except BackupError as exc:
        assert exc.code == "BACKUP_INCOMPATIBLE"


def test_stale_jobs_become_interrupted(db_session):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=2)
    source = SourceItem(id=uuid.uuid4(), source_type="TEXT", display_name="stale", status="STORED", privacy_level="PRIVATE", created_at=old, updated_at=old)
    db_session.add(source)
    db_session.flush()
    extraction = ExtractionRun(id=uuid.uuid4(), source_item_id=source.id, status="RUNNING", trigger="MANUAL", created_at=old, updated_at=old)
    db_session.add(extraction)
    db_session.flush()
    document = ExtractedDocument(
        id=uuid.uuid4(), extraction_run_id=extraction.id, source_item_id=source.id, extractor_type="text", extractor_version="1",
        status="SUCCEEDED", plain_text="stale", metadata_json={}, content_hash="a" * 64, created_at=old, updated_at=old,
    )
    db_session.add(document)
    db_session.flush()
    analysis = AnalysisRun(
        id=uuid.uuid4(), source_item_id=source.id, extracted_document_id=document.id, provider_type="FAKE", model_name="fake",
        prompt_name="analysis", prompt_version="1", status="RUNNING", metadata_json={}, started_at=old, created_at=old,
    )
    brief = Brief(
        id=uuid.uuid4(), start_date=old.date(), end_date=old.date(), date_basis="COLLECTED_AT", detail_level="STANDARD", status="RUNNING",
        prompt_name="brief-general", prompt_version="1", filters_json={}, exclusion_reasons_json={}, structured_result_json={}, created_at=old,
    )
    fresh = Brief(
        id=uuid.uuid4(), start_date=now.date(), end_date=now.date(), date_basis="COLLECTED_AT", detail_level="STANDARD", status="RUNNING",
        prompt_name="brief-general", prompt_version="1", filters_json={}, exclusion_reasons_json={}, structured_result_json={}, created_at=now,
    )
    ask_session = AskSession(id=uuid.uuid4(), title="stale", created_at=old, updated_at=old)
    ask_turn = AskTurn(
        id=uuid.uuid4(),
        session_id=ask_session.id,
        question="stale question",
        status="RUNNING",
        retrieval_query="stale question",
        filters_json={},
        created_at=old,
    )
    db_session.add_all([analysis, brief, fresh, ask_session, ask_turn])
    db_session.flush()
    settings = get_settings().model_copy(update={"job_stale_after_seconds": 60})
    result = recover_stale_jobs(db_session, settings, now=now)
    assert result["count"] >= 3
    assert extraction.status == "FAILED" and extraction.error_code == "WORKER_INTERRUPTED"
    assert analysis.status == "FAILED" and analysis.error_code == "WORKER_INTERRUPTED"
    assert brief.status == "FAILED" and brief.error_code == "WORKER_INTERRUPTED"
    assert fresh.status == "RUNNING"
    assert ask_turn.status == "FAILED" and ask_turn.error_code == "WORKER_INTERRUPTED"


def test_storage_audit_reports_missing_without_deleting(db_session, tmp_path: Path):
    source = SourceItem(id=uuid.uuid4(), source_type="FILE", display_name="missing", status="STORED", privacy_level="PRIVATE", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    db_session.add(source)
    db_session.flush()
    asset = SourceAsset(
        id=uuid.uuid4(), source_item_id=source.id, original_filename="gone.bin", stored_path=str(tmp_path / "missing.bin"),
        mime_type="application/octet-stream", size_bytes=4, sha256=uuid.uuid4().hex + uuid.uuid4().hex[:32], created_at=datetime.now(timezone.utc),
    )
    db_session.add(asset)
    db_session.flush()
    before = db_session.get(SourceAsset, asset.id).id
    report = audit_storage(db_session, get_settings())
    assert report["status"] == "FAIL"
    assert str(asset.id) in {item["asset_id"] for item in report["missing"]}
    assert db_session.get(SourceAsset, before) is not None


def test_storage_audit_resolves_relative_assets_under_raw_storage_root(db_session, tmp_path: Path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    raw_root = tmp_path / "raw"
    stored_file = raw_root / "ab" / "cd" / "fixture.bin"
    stored_file.parent.mkdir(parents=True)
    body = b"relative raw asset"
    stored_file.write_bytes(body)
    source = SourceItem(
        id=uuid.uuid4(), source_type="FILE", display_name="fixture", status="STORED",
        privacy_level="PRIVATE", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    db_session.add(source)
    db_session.flush()
    asset = SourceAsset(
        id=uuid.uuid4(), source_item_id=source.id, original_filename="fixture.bin",
        stored_path="ab/cd/fixture.bin", mime_type="application/octet-stream", size_bytes=len(body),
        sha256=hashlib.sha256(body).hexdigest(), created_at=datetime.now(timezone.utc),
    )
    db_session.add(asset)
    db_session.flush()

    settings = get_settings().model_copy(update={"raw_storage_subdir": "raw"})
    report = audit_storage(db_session, settings)

    assert str(asset.id) not in {item["asset_id"] for item in report["missing"]}
    assert str(stored_file.resolve()) not in report["orphan"]


def test_data_audit_and_system_status(db_session, monkeypatch):
    assert audit_data(db_session)["status"] == "PASS"
    monkeypatch.setattr("app.services.maintenance.system.shutil.disk_usage", lambda _path: type("Usage", (), {"used": 10, "free": 1})())
    status = system_status(db_session, get_settings().model_copy(update={"disk_low_warning_bytes": 100}))
    assert status["version"] == APP_VERSION
    assert status["disk"]["warning"] is True
    assert "sources" in status["counts"]
    ready = readiness(db_session)
    assert "postgres" in ready["checks"]
    monkeypatch.setattr("app.services.maintenance.system._known_revisions", lambda: set())
    blocked = readiness(db_session)
    assert blocked["ready"] is False
    assert blocked["error"] == "DATABASE_MIGRATION_REQUIRED"


def test_fallback_respects_privacy_and_default_off():
    disabled = get_settings().model_copy(update={"llm_enable_fake": True, "llm_provider_fallback_enabled": False, "llm_fallback_provider": "FAKE"})
    assert select_fallback(disabled, "DEEPSEEK", "PUBLIC") is None
    enabled = disabled.model_copy(update={"llm_provider_fallback_enabled": True})
    assert select_fallback(enabled, "DEEPSEEK", "PUBLIC") is None
    cloud = enabled.model_copy(update={"llm_fallback_provider": "DEEPSEEK", "deepseek_base_url": "https://api.deepseek.com", "deepseek_model": "m", "deepseek_api_key": "not-used"})
    assert select_fallback(cloud, "FAKE", "SENSITIVE") is None


def test_path_safety_portable_export_and_atomic_file(db_session, tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    assert resolve_under(root, "child.txt") == (root / "child.txt").resolve()
    try:
        resolve_under(root, "../outside.txt")
    except ValueError as exc:
        assert str(exc) == "PATH_OUTSIDE_ROOT"
    destination = tmp_path / "portable"
    brief = Brief(
        id=uuid.uuid4(),
        title="portable",
        start_date=datetime.now(timezone.utc).date(),
        end_date=datetime.now(timezone.utc).date(),
        date_basis="COLLECTED_AT",
        detail_level="STANDARD",
        status="SUCCEEDED",
        prompt_name="brief",
        prompt_version="1.0.0",
        filters_json={},
        exclusion_reasons_json={},
        content_markdown="简报正文",
        structured_result_json={},
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(brief)
    db_session.flush()
    export_library(db_session, destination)
    assert (destination / "sources.json").is_file()
    assert (destination / "manifest.json").is_file()
    assert (destination / "markdown" / f"{brief.id}.md").read_text(encoding="utf-8") == "简报正文"
    assert json.loads((destination / "manifest.json").read_text(encoding="utf-8"))["include_raw_files"] is False
    exported = cache_export(f"atomic-{uuid.uuid4().hex}.md", b"done")
    assert exported.read_bytes() == b"done"
    assert not exported.with_name(exported.name + ".partial").exists()
    exported.unlink(missing_ok=True)


def test_logs_redact_secrets(tmp_path, monkeypatch):
    import logging

    assert "test-credential" not in redact("api_key=test-credential")
    logger = logging.getLogger("insighthub")
    logger.handlers.clear()
    monkeypatch.setattr("app.core.logging.PROJECT_ROOT", tmp_path)
    log_event("provider_call", message="authorization=Bearer test-credential")
    text = (tmp_path / "data" / "logs" / "insighthub.log").read_text(encoding="utf-8")
    assert "test-credential" not in text
    assert "provider_call" in text
    logger.handlers.clear()
