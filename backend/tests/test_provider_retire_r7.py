import uuid
from types import SimpleNamespace

import pytest
from fastapi import Request
from sqlalchemy import select

from app.api.analysis import retire_provider
from app.models.analysis import LLMModelDeployment, LLMProviderConfig, LLMWorkflowRoute
from app.services.analysis.service import AnalysisError


def _request() -> Request:
    return Request({"type": "http", "headers": [], "client": ("testclient", 12345), "method": "POST", "path": "/"})


def _legacy_provider(db_session):
    provider = db_session.scalar(select(LLMProviderConfig).where(LLMProviderConfig.provider_type == "SILICONFLOW"))
    assert provider is not None
    deployment = LLMModelDeployment(
        id=uuid.uuid4(), provider_config_id=provider.id, display_name="Legacy model",
        model_id="legacy-model", enabled=True, capabilities_json={},
    )
    db_session.add(deployment)
    db_session.flush()
    return provider, deployment


def _zai_deployment(db_session):
    provider = db_session.scalar(select(LLMProviderConfig).where(LLMProviderConfig.provider_type == "ZAI"))
    if provider is None:
        provider = LLMProviderConfig(
            id=uuid.uuid4(), name="ZAI", provider_type="ZAI", base_url="https://open.bigmodel.cn/api/paas/v4",
            model="glm-5.3-flash", is_local=False, enabled=True, api_key_env="ZAI_API_KEY",
            capabilities_json={}, is_default=False,
        )
        db_session.add(provider)
        db_session.flush()
    deployment = LLMModelDeployment(
        id=uuid.uuid4(), provider_config_id=provider.id, display_name="GLM Flash",
        model_id="glm-5.3-flash", enabled=True, capabilities_json={},
    )
    db_session.add(deployment)
    db_session.flush()
    return deployment


def test_retire_provider_refuses_while_a_workflow_still_uses_it(db_session):
    provider, deployment = _legacy_provider(db_session)
    original_enabled = provider.enabled
    route = db_session.get(LLMWorkflowRoute, "ANALYSIS")
    if route is None:
        route = LLMWorkflowRoute(workflow="ANALYSIS", deployment_id=deployment.id)
        db_session.add(route)
    else:
        route.deployment_id = deployment.id
    db_session.flush()

    with pytest.raises(AnalysisError) as exc:
        retire_provider(provider.id, _request(), SimpleNamespace(session=db_session))

    assert exc.value.code == "ROUTE_IN_USE"
    assert db_session.get(LLMProviderConfig, provider.id).enabled is original_enabled
    assert db_session.get(LLMModelDeployment, deployment.id).archived_at is None


def test_retire_provider_archives_configs_but_keeps_historical_identity(db_session):
    provider, deployment = _legacy_provider(db_session)
    replacement = _zai_deployment(db_session)
    for route in db_session.scalars(select(LLMWorkflowRoute)):
        route.deployment_id = replacement.id
    db_session.flush()

    result = retire_provider(provider.id, _request(), SimpleNamespace(session=db_session))

    assert result["retired"] is True
    assert result["history_preserved"] is True
    assert db_session.get(LLMProviderConfig, provider.id).enabled is False
    archived = db_session.get(LLMModelDeployment, deployment.id)
    assert archived.enabled is False
    assert archived.archived_at is not None
    assert db_session.scalar(select(LLMProviderConfig.id).where(LLMProviderConfig.id == provider.id)) == provider.id
