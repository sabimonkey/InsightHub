from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db, get_engine
from app.main import app
from app.services.ingestion.service import IngestionService


@pytest.fixture(autouse=True)
def isolate_local_providers(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("EMBEDDING_ENABLE_FAKE", "false")
    monkeypatch.setenv("LOCAL_EMBEDDING_BASE_URL", "")
    monkeypatch.setenv("LOCAL_EMBEDDING_MODEL", "")
    monkeypatch.setenv("GENERIC_EMBEDDING_BASE_URL", "")
    monkeypatch.setenv("GENERIC_EMBEDDING_MODEL", "")
    monkeypatch.setenv("GENERIC_EMBEDDING_API_KEY", "")
    monkeypatch.setenv("SILICONFLOW_EMBEDDING_BASE_URL", "")
    monkeypatch.setenv("SILICONFLOW_EMBEDDING_MODEL", "")
    monkeypatch.setenv("SILICONFLOW_EMBEDDING_API_KEY", "")
    monkeypatch.setenv("LLM_ENABLE_FAKE", "false")
    monkeypatch.setenv("LLM_TEST_LEGACY_PROVIDERS", "true")
    monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "")
    monkeypatch.setenv("INSIGHTHUB_SYSTEM_SCOPE", "AUTOMATION_TEST")
    monkeypatch.setenv("LMSTUDIO_MODEL", "")
    monkeypatch.setenv("PIPELINE_AUTO_ANALYSIS_ENABLED", "false")
    monkeypatch.setenv("COVER_AUTO_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture
def db_session() -> Iterator[Session]:
    connection = get_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def raw_root(tmp_path: Path) -> Path:
    root = tmp_path / "raw"
    root.mkdir()
    return root


@pytest.fixture
def client(db_session: Session, raw_root: Path) -> Iterator[TestClient]:
    from app.api.deps import get_extraction_service, get_ingestion_service

    class _SkipExtraction:
        def schedule(self, *_args, **_kwargs):
            return None

        def current_view(self, *_args, **_kwargs):
            return None, None, []

    def override_service() -> Iterator[IngestionService]:
        yield IngestionService(db_session, raw_root, max_upload_size_bytes=1024)

    def override_extraction() -> Iterator[_SkipExtraction]:
        yield _SkipExtraction()

    def override_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_ingestion_service] = override_service
    app.dependency_overrides[get_extraction_service] = override_extraction
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
