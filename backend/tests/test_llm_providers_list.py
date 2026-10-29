from sqlalchemy import select

from app.core.config import get_settings
from app.models.analysis import LLMProviderConfig
from app.services.llm.registry import sync_provider_rows
from app.services.system_scope import AUTOMATION_TEST_SCOPE, creation_scope_from_settings


def _visible_provider_rows(session, settings):
    scope = creation_scope_from_settings(settings)
    rows = list(session.scalars(select(LLMProviderConfig)))
    visible = []
    for row in rows:
        if row.provider_type == "FAKE":
            if scope != AUTOMATION_TEST_SCOPE or not settings.llm_enable_fake:
                continue
        visible.append(row)
    return visible


def test_fake_hidden_in_user_scope(db_session, monkeypatch):
    monkeypatch.setenv("LLM_ENABLE_FAKE", "true")
    monkeypatch.setenv("INSIGHTHUB_SYSTEM_SCOPE", "USER")
    get_settings.cache_clear()
    settings = get_settings()
    sync_provider_rows(db_session, settings)
    visible = _visible_provider_rows(db_session, settings)
    assert all(row.provider_type != "FAKE" for row in visible)
    get_settings.cache_clear()


def test_fake_visible_in_automation_scope(db_session, monkeypatch):
    monkeypatch.setenv("LLM_ENABLE_FAKE", "true")
    monkeypatch.setenv("INSIGHTHUB_SYSTEM_SCOPE", "AUTOMATION_TEST")
    get_settings.cache_clear()
    settings = get_settings()
    sync_provider_rows(db_session, settings)
    visible = _visible_provider_rows(db_session, settings)
    assert any(row.provider_type == "FAKE" for row in visible)
    get_settings.cache_clear()
