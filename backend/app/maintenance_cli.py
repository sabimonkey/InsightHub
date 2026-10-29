import argparse
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, func, select, text

from app.core.config import PROJECT_ROOT, get_settings
from app.db.session import get_engine, get_sessionmaker
from app.services.maintenance.audit import audit_data, audit_storage
from app.services.maintenance.backup import BackupError, create_backup, restore_backup
from app.services.maintenance.portable import export_library
from app.version import APP_VERSION


def _session():
    return get_sessionmaker()()


def _backup(args: argparse.Namespace) -> int:
    destination = Path(args.dest) if args.dest else PROJECT_ROOT / "data" / "backup" / datetime.now(timezone.utc).strftime("backup_%Y%m%dT%H%M%SZ")
    session = _session()
    try:
        path = create_backup(destination, session)
    except BackupError as exc:
        print(exc.code)
        return 1
    finally:
        session.close()
    print(path)
    return 0


def _restore(args: argparse.Namespace) -> int:
    if not args.confirm:
        print("RESTORE_CONFIRMATION_REQUIRED")
        return 1
    session = _session()
    try:
        if not args.skip_safety_backup:
            safety = PROJECT_ROOT / "data" / "backup" / datetime.now(timezone.utc).strftime("pre_restore_%Y%m%dT%H%M%SZ")
            create_backup(safety, session)
            print(f"safety_backup={safety}")
        result = restore_backup(Path(args.path), confirm=True)
    except BackupError as exc:
        print(exc.code)
        return 1
    finally:
        session.close()
    print(result["restored"])
    return 0


def _audit_storage() -> int:
    session = _session()
    try:
        report = audit_storage(session)
    finally:
        session.close()
    print(report["status"])
    print(report["counts"])
    for item in report["missing"]:
        print(f"missing asset={item['asset_id']} source={item['source_id']}")
    for item in report["corrupt"]:
        print(f"corrupt asset={item['asset_id']} source={item['source_id']}")
    for item in report["orphan"]:
        print(f"orphan {item}")
    return 0 if report["status"] == "PASS" else 1


def _audit_data() -> int:
    session = _session()
    try:
        report = audit_data(session)
    finally:
        session.close()
    print(report["status"])
    print(report["counts"])
    return 0 if report["status"] == "PASS" else 1


def _portable(args: argparse.Namespace) -> int:
    destination = Path(args.dest)
    session = _session()
    try:
        export_library(session, destination, include_raw_files=args.include_raw_files)
    finally:
        session.close()
    print(destination)
    return 0


def _env_report() -> int:
    settings = get_settings()
    print(f"os={platform.platform()}")
    print(f"python={platform.python_version()}")
    print(f"app_version={APP_VERSION}")
    npm_command = ["npm.cmd", "--version"] if os.name == "nt" else ["npm", "--version"]
    for name, command in (("node", ["node", "--version"]), ("npm", npm_command), ("docker", ["docker", "--version"]), ("git", ["git", "rev-parse", "--short", "HEAD"])):
        try:
            result = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)
            print(f"{name}={result.stdout.strip() or result.stderr.strip()}")
        except OSError:
            print(f"{name}=missing")
    print("postgres_container=insighthub-postgres")
    session = _session()
    try:
        revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    except Exception:
        revision = None
    finally:
        session.close()
    print(f"alembic={revision}")
    print(f"llm_configured={'yes' if settings.llm_default_provider or settings.llm_enable_fake else 'no'}")
    print(f"embedding_configured={'yes' if settings.embedding_enable_fake or settings.local_embedding_model else 'no'}")
    return 0


def _secret_scan() -> int:
    import re

    token = re.compile(r"(?:sk-|AKIA)[A-Za-z0-9]{24,}")
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    flagged = []
    stdout = tracked.stdout or ""
    for relative in stdout.splitlines():
        name = Path(relative).name
        if name == ".env" or (name.startswith(".env.") and "example" not in name):
            flagged.append(relative)
            continue
        path = PROJECT_ROOT / relative
        if not path.is_file() or path.stat().st_size > 1_000_000:
            continue
        try:
            text_value = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if token.search(text_value):
            flagged.append(relative)
    if flagged:
        print("SECRET_SCAN_FAIL")
        for item in flagged:
            print(item)
        return 1
    print("SECRET_SCAN_PASS")
    return 0


def _alembic_upgrade(url: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = url
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=PROJECT_ROOT / "backend", env=env, capture_output=True, text=True)
    if result.returncode != 0:
        secret = url.split("@", 1)[0]
        print(result.stderr.replace(secret, "[redacted]")[-800:])
        raise RuntimeError("ALEMBIC_UPGRADE_FAILED")


def _release() -> int:
    import hashlib
    import io

    from app.models.analysis import Claim
    from app.models.organization import Entity, Topic
    from app.models.retrieval import AskSession, AskTurn
    from app.models.source_asset import SourceAsset
    from app.models.source_item import SourceItem
    from app.models.synthesis import Brief
    from app.services.analysis.service import AnalysisService
    from app.services.extraction.service import ExtractionService
    from app.services.ingestion.service import IngestionService
    from app.services.llm.provider import FakeLLMProvider
    from app.services.organization.service import OrganizationService
    from app.services.retrieval.search import SearchService

    original = os.environ.get("DATABASE_URL", get_settings().database_url)
    main = create_engine(original)
    with main.connect() as connection:
        before = connection.execute(text("SELECT count(*) FROM source_items")).scalar_one()
    _alembic_upgrade(original)
    with main.connect() as connection:
        after = connection.execute(text("SELECT count(*) FROM source_items")).scalar_one()
    main.dispose()
    if before != after:
        print("EXISTING_DB_CHANGED")
        return 1
    print(f"existing_db_sources={after}")
    admin = create_engine(original, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'insighthub_release' AND pid <> pg_backend_pid()"))
        connection.execute(text("DROP DATABASE IF EXISTS insighthub_release"))
        connection.execute(text("CREATE DATABASE insighthub_release"))
    admin.dispose()
    release_url = original.rsplit("/", 1)[0] + "/insighthub_release"
    os.environ["DATABASE_URL"] = release_url
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    _alembic_upgrade(release_url)
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    raw = PROJECT_ROOT / "data" / "backup" / "_release_raw"
    extracted = PROJECT_ROOT / "data" / "backup" / "_release_extracted"
    backup_dir = PROJECT_ROOT / "data" / "backup" / "_release_backup"
    session = None
    shutil.rmtree(raw, ignore_errors=True)
    shutil.rmtree(extracted, ignore_errors=True)
    shutil.rmtree(backup_dir, ignore_errors=True)
    raw.mkdir(parents=True)
    extracted.mkdir(parents=True)
    session = get_sessionmaker()()
    try:
        OrganizationService(session).ensure_default_categories()
        session.commit()
        payload = b"release install fact about local knowledge"
        created = IngestionService(session, raw, max_upload_size_bytes=200_000).ingest_file("release.md", io.BytesIO(payload), "text/markdown")
        ExtractionService(session, raw, extracted, inline=True, chunk_max_chars=500, chunk_overlap_chars=20, max_pdf_pages=2, web_timeout=1, web_max_bytes=1000, web_max_redirects=1).schedule(created.source_item.id, "MANUAL", force=True)
        settings = get_settings().model_copy(update={"llm_enable_fake": True, "llm_default_provider": "FAKE"})
        run = AnalysisService(session, inline=True, settings=settings, providers={"FAKE": FakeLLMProvider()}).start(created.source_item.id)
        if run.status not in {"SUCCEEDED", "PARTIAL"}:
            print(f"FRESH_ANALYSIS_{run.status}")
            return 1
        found = SearchService(session, settings).search("release", mode="keyword")
        if not found.get("results"):
            print("FRESH_SEARCH_EMPTY")
            return 1
        now = datetime.now(timezone.utc)
        session.add(Topic(name="Release Topic", normalized_name="release-topic", created_at=now, updated_at=now))
        session.add(Entity(name="Release Entity", normalized_name="release-entity", entity_type="OTHER", created_at=now, updated_at=now))
        ask = AskSession(title="release", created_at=now, updated_at=now)
        session.add(ask)
        session.flush()
        session.add(AskTurn(session_id=ask.id, question="release question", status="SUCCEEDED", retrieval_query="release", filters_json={}, created_at=now))
        session.add(
            Brief(
                start_date=now.date(),
                end_date=now.date(),
                date_basis="COLLECTED_AT",
                detail_level="STANDARD",
                status="SUCCEEDED",
                prompt_name="brief-general",
                prompt_version="1.0.0",
                filters_json={},
                exclusion_reasons_json={},
                structured_result_json={},
                content_markdown="release brief",
                created_at=now,
            )
        )
        session.commit()
        asset = created.asset
        source_id = created.source_item.id
        stored = asset.stored_path
        digest = asset.sha256
        create_backup(backup_dir, session, settings, raw_root=raw, extracted_root=extracted)
        session.close()
        reset = create_engine(release_url, isolation_level="AUTOCOMMIT")
        with reset.connect() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        reset.dispose()
        shutil.rmtree(raw)
        raw.mkdir()
        get_engine.cache_clear()
        get_sessionmaker.cache_clear()
        restored = restore_backup(backup_dir, settings, confirm=True, raw_root=raw, extracted_root=extracted)
        print(restored["schema_revision"])
        session = get_sessionmaker()()
        source = session.get(SourceItem, source_id)
        restored_asset = session.scalar(select(SourceAsset).where(SourceAsset.source_item_id == source_id))
        if source is None or restored_asset is None or session.scalar(select(func.count()).select_from(Brief)) < 1:
            print("RESTORE_MISMATCH")
            return 1
        if session.scalar(select(func.count()).select_from(Claim)) < 1:
            print("RESTORE_CLAIM_MISMATCH")
            return 1
        if session.scalar(select(func.count()).select_from(Topic)) < 1 or session.scalar(select(func.count()).select_from(Entity)) < 1:
            print("RESTORE_TAXONOMY_MISMATCH")
            return 1
        if session.scalar(select(func.count()).select_from(AskTurn)) != 1:
            print("RESTORE_ASK_MISMATCH")
            return 1
        restored_file = raw / stored
        if hashlib.sha256(restored_file.read_bytes()).hexdigest() != digest:
            print("RESTORE_HASH_MISMATCH")
            return 1
        print("RELEASE_CHECK_PASS")
        return 0
    finally:
        if session is not None:
            session.close()
        get_engine.cache_clear()
        get_sessionmaker.cache_clear()
        os.environ["DATABASE_URL"] = original
        get_settings.cache_clear()
        try:
            admin = create_engine(original, isolation_level="AUTOCOMMIT")
            with admin.connect() as connection:
                connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'insighthub_release' AND pid <> pg_backend_pid()"))
                connection.execute(text("DROP DATABASE IF EXISTS insighthub_release"))
            admin.dispose()
        except Exception:
            print("RELEASE_DB_CLEANUP_SKIPPED")
        shutil.rmtree(raw, ignore_errors=True)
        shutil.rmtree(extracted, ignore_errors=True)
        shutil.rmtree(backup_dir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup")
    backup.add_argument("--dest")
    restore = sub.add_parser("restore")
    restore.add_argument("--path", required=True)
    restore.add_argument("--confirm", action="store_true")
    restore.add_argument("--skip-safety-backup", action="store_true")
    sub.add_parser("audit-storage")
    sub.add_parser("audit-data")
    portable = sub.add_parser("portable")
    portable.add_argument("--dest", required=True)
    portable.add_argument("--include-raw-files", action="store_true")
    sub.add_parser("env-report")
    sub.add_parser("secret-scan")
    sub.add_parser("release")
    args = parser.parse_args(argv)
    commands = {
        "backup": _backup,
        "restore": _restore,
        "audit-storage": lambda _args: _audit_storage(),
        "audit-data": lambda _args: _audit_data(),
        "portable": _portable,
        "env-report": lambda _args: _env_report(),
        "secret-scan": lambda _args: _secret_scan(),
        "release": lambda _args: _release(),
    }
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
