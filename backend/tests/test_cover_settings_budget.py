from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.analysis import LLMProviderConfig
from app.services.cover.budget import lock_monthly_budget
from app.services.cover.settings_prefs import load_cover_prefs


@pytest.fixture(autouse=True)
def keep_settings_writes_in_the_outer_test_transaction(db_session, monkeypatch):
    # The production service commits settings. In this API test, keep its
    # writes as flushes so the shared PostgreSQL fixture can roll them back.
    monkeypatch.setattr(db_session, "commit", db_session.flush)


def _minimax_provider(db_session):
    provider = db_session.scalar(
        select(LLMProviderConfig).where(LLMProviderConfig.provider_type == "MINIMAX_IMAGE")
    )
    if provider is None:
        provider = LLMProviderConfig(
            id=uuid.uuid4(),
            name="MiniMax",
            provider_type="MINIMAX_IMAGE",
            base_url="https://api.minimax.cn",
            model="image-01",
            is_local=False,
            enabled=True,
            api_key_env="MINIMAX_API_KEY",
            capabilities_json={"cover_automation": {"monthly_budget": 100}},
        )
        db_session.add(provider)
        db_session.flush()
    caps = dict(provider.capabilities_json or {})
    automation = dict(caps.get("cover_automation") or {})
    automation["monthly_budget"] = 100
    caps["cover_automation"] = automation
    provider.capabilities_json = caps
    db_session.flush()
    return provider


def test_cover_budget_200_persists_and_is_used_by_runtime(client, db_session):
    provider = _minimax_provider(db_session)

    before = client.get("/api/cover/settings")
    assert before.status_code == 200
    assert before.json()["monthly_budget"] == 100
    assert before.json()["budget_range"] == {"min": 1, "max": 500}
    schema = client.get("/openapi.json").json()["components"]["schemas"]["CoverSettingsPatch"]["properties"]["monthly_budget"]["anyOf"][0]
    assert schema["minimum"] == 1
    assert schema["maximum"] == 500

    saved = client.patch(
        "/api/cover/settings",
        json={"monthly_budget": 200},
        headers={"origin": "http://127.0.0.1:5174"},
    )
    assert saved.status_code == 200
    assert saved.json()["ok"] is True
    assert saved.json()["monthly_budget"] == 200
    assert saved.json()["budget_kind"] == "insighthub_local_safety_cap"

    db_session.expire_all()
    reread = client.get("/api/cover/settings")
    assert reread.status_code == 200
    assert reread.json()["monthly_budget"] == 200
    assert load_cover_prefs(db_session).monthly_budget == 200
    # A fresh ORM session sees the persisted JSONB value, matching the worker
    # process's independent database read without touching production settings.
    with Session(bind=db_session.connection(), join_transaction_mode="create_savepoint") as reloaded_session:
        assert load_cover_prefs(reloaded_session).monthly_budget == 200
    used, budget = lock_monthly_budget(db_session, provider.id)
    assert used >= 0
    assert budget == 200


@pytest.mark.parametrize("value", [0, 501, -1, 200.5])
def test_cover_budget_rejects_out_of_range_without_changing_saved_value(client, db_session, value):
    _minimax_provider(db_session)
    assert client.patch(
        "/api/cover/settings",
        json={"monthly_budget": 200},
        headers={"origin": "http://127.0.0.1:5174"},
    ).status_code == 200

    rejected = client.patch(
        "/api/cover/settings",
        json={"monthly_budget": value},
        headers={"origin": "http://127.0.0.1:5174"},
    )
    assert rejected.status_code == 422
    assert client.get("/api/cover/settings").json()["monthly_budget"] == 200


def test_cover_budget_mutation_remains_local_only(client, db_session):
    _minimax_provider(db_session)
    response = client.patch("/api/cover/settings", json={"monthly_budget": 200})
    assert response.status_code == 200


def test_cover_budget_save_failure_returns_error_and_preserves_last_value(client, db_session, monkeypatch):
    _minimax_provider(db_session)

    def fail_before_commit(*_args, **_kwargs):
        raise ValueError("PROVIDER_NOT_CONFIGURED")

    monkeypatch.setattr("app.api.cover.save_cover_monthly_budget", fail_before_commit)
    response = client.patch(
        "/api/cover/settings",
        json={"monthly_budget": 200},
        headers={"origin": "http://127.0.0.1:5174"},
    )
    assert response.status_code == 409
    assert client.get("/api/cover/settings").json()["monthly_budget"] == 100
