import json
from collections.abc import Iterator

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_analysis_service, get_db
from app.core.config import get_settings
from app.main import app
from app.services.analysis.service import AnalysisService
from app.services.llm.credential_resolver import resolve_api_key
from app.services.llm.registry import build_provider, provider_specs
from app.services.secrets.vault import clear_vault_secret, write_vault_secret


@pytest.fixture
def credential_master_key(monkeypatch, db_session):
    key = Fernet.generate_key()
    monkeypatch.setenv("INSIGHTHUB_CREDENTIALS_MASTER_KEY", key.decode("ascii"))
    monkeypatch.setattr("app.services.secrets.vault._load_master_key_bytes", lambda: key)
    monkeypatch.setattr("app.services.secrets.vault._ensure_master_key_bytes", lambda: key)
    from app.models.analysis import LLMProviderCredential

    db_session.query(LLMProviderCredential).delete()
    db_session.flush()
    get_settings.cache_clear()
    yield key
    get_settings.cache_clear()


def test_vault_encrypt_roundtrip(db_session, credential_master_key):
    write_vault_secret(db_session, "DEEPSEEK", "test-credential")
    resolved = resolve_api_key("DEEPSEEK", "DEEPSEEK_API_KEY", get_settings(), db_session)
    assert resolved.value == "test-credential"
    assert resolved.source == "vault"


def test_env_overrides_vault(db_session, credential_master_key, monkeypatch):
    write_vault_secret(db_session, "DEEPSEEK", "test-credential")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-credential")
    get_settings.cache_clear()
    resolved = resolve_api_key("DEEPSEEK", "DEEPSEEK_API_KEY", get_settings(), db_session)
    assert resolved.value == "test-credential"
    assert resolved.source == "environment"
    get_settings.cache_clear()


def test_clear_vault_keeps_env(db_session, credential_master_key, monkeypatch):
    write_vault_secret(db_session, "MINIMAX_IMAGE", "test-credential")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-credential")
    get_settings.cache_clear()
    clear_vault_secret(db_session, "MINIMAX_IMAGE")
    resolved = resolve_api_key("MINIMAX_IMAGE", "MINIMAX_API_KEY", get_settings(), db_session)
    assert resolved.value == "test-credential"
    assert resolved.source == "environment"
    get_settings.cache_clear()


@pytest.fixture
def analysis_client(db_session: Session) -> Iterator[TestClient]:
    settings = get_settings()

    def override_db() -> Iterator[Session]:
        yield db_session

    def override_analysis() -> Iterator[AnalysisService]:
        yield AnalysisService(db_session, inline=settings.analysis_inline, settings=settings, enqueue=lambda *_a, **_k: None)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_analysis_service] = override_analysis
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_save_credential_api_no_echo(db_session, credential_master_key, monkeypatch, analysis_client):
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    get_settings.cache_clear()
    from app.services.llm.registry import sync_provider_rows

    settings = get_settings()
    rows = sync_provider_rows(db_session, settings)
    zai = next(r for r in rows if r.provider_type == "ZAI")
    secret = "TEST_ONLY_SECRET_SENTINEL"
    response = analysis_client.put(
        f"/api/llm/providers/{zai.id}/credential",
        json={"api_key": secret},
        headers={"Origin": "http://127.0.0.1:5174"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["credential_source"] == "vault"
    assert secret not in json.dumps(body)
    listed = analysis_client.get("/api/llm/providers").json()
    zai_view = next(item for item in listed if item["provider_type"] == "ZAI")
    assert zai_view["api_key_state"] == "configured"
    assert zai_view["credential_source"] == "vault"
    assert secret not in json.dumps(listed)
    get_settings.cache_clear()


def test_build_provider_uses_vault(db_session, credential_master_key, monkeypatch):
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    get_settings.cache_clear()
    write_vault_secret(db_session, "ZAI", "test-credential")
    settings = get_settings()
    spec = next(item for item in provider_specs(settings, db_session) if item.provider_type == "ZAI")
    provider = build_provider(spec, settings, session=db_session)
    assert provider.api_key == "test-credential"
    get_settings.cache_clear()


def test_credential_api_rejects_bad_origin(db_session, credential_master_key, analysis_client):
    from app.services.llm.registry import sync_provider_rows

    rows = sync_provider_rows(db_session, get_settings())
    zai = next(r for r in rows if r.provider_type == "ZAI")
    response = analysis_client.put(
        f"/api/llm/providers/{zai.id}/credential",
        json={"api_key": "test-credential"},
        headers={"Origin": "http://evil.example"},
    )
    assert response.status_code == 403
    get_settings.cache_clear()
