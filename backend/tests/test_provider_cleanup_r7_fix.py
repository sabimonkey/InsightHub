import pytest

from app.core.config import Settings
from app.models.analysis import LLMModelDeployment, LLMProviderConfig
from app.services.analysis.service import AnalysisService
from app.services.llm import credential_resolver, registry
from app.services.llm.credential_resolver import ResolvedApiKey
from app.services.llm.routing import RETIRED_PROVIDER_TYPES, RoutingError, _fake_allowed, resolve_workflow
from app.api.analysis import list_providers
from sqlalchemy import select


def _settings(**overrides):
    values = {
        "llm_enable_fake": False,
        "llm_default_provider": "LOCAL_OPENAI_COMPATIBLE",
        "insighthub_system_scope": "USER",
        "zai_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "zai_model": "glm-5.3-flash",
        "zai_api_key": "",
        "lmstudio_base_url": "http://127.0.0.1:1234/v1",
        "lmstudio_model": "qwen2.5-14b-instruct",
        "deepseek_base_url": "https://api.deepseek.com/v1",
        "deepseek_model": "legacy-model",
        "deepseek_api_key": "legacy-key-must-not-route",
        "siliconflow_base_url": "https://api.siliconflow.cn/v1",
        "siliconflow_model": "legacy-model",
        "siliconflow_api_key": "legacy-key-must-not-route",
        "generic_llm_base_url": "https://example.invalid/v1",
        "generic_llm_model": "legacy-model",
        "generic_llm_api_key": "legacy-key-must-not-route",
    }
    values.update(overrides)
    return Settings(**values)


def _no_key(*_args, **_kwargs):
    return ResolvedApiKey("", "none")


def test_keyless_zai_card_and_both_models_hide_legacy_provider_instances(db_session, monkeypatch):
    monkeypatch.setattr(registry, "resolve_api_key", _no_key)
    monkeypatch.setattr(credential_resolver, "resolve_api_key", _no_key)
    settings = _settings()
    views = list_providers(AnalysisService(db_session, inline=False, settings=settings))
    by_type = {item.provider_type: item for item in views}

    assert set(by_type) == {"ZAI", "MINIMAX_IMAGE"}
    zai = by_type["ZAI"]
    assert zai.name == "智谱 GLM"
    assert zai.base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert zai.configured is False
    assert zai.api_key_state == "not_configured"
    assert {deployment.model_id for deployment in zai.deployments} >= {"glm-5.3-flash", "glm-5.3-flashx"}


def test_keyless_route_is_configuration_required_and_never_uses_legacy_or_fake(db_session, monkeypatch):
    monkeypatch.setattr(registry, "resolve_api_key", _no_key)
    settings = _settings(llm_enable_fake=True, llm_default_provider="FAKE")
    # FAKE must not be eligible for a USER-scoped configuration.
    assert not _fake_allowed(settings)
    with pytest.raises(RoutingError) as error:
        resolve_workflow(db_session, settings, "ANALYSIS")
    assert error.value.code == "CONFIGURATION_REQUIRED"

    for provider_type in RETIRED_PROVIDER_TYPES:
        with pytest.raises(RoutingError) as retired:
            resolve_workflow(db_session, settings, "ANALYSIS", provider_type)
        assert retired.value.code == "PROVIDER_RETIRED"


def test_missing_workflow_routes_seed_to_zai_without_key_or_local_fallback(db_session, monkeypatch):
    from app.services.llm.routing import _ensure_routes, WORKFLOWS
    from app.models.analysis import LLMWorkflowRoute

    monkeypatch.setattr(registry, "resolve_api_key", _no_key)
    settings = _settings()
    db_session.execute(LLMWorkflowRoute.__table__.delete())
    db_session.flush()
    _ensure_routes(db_session, settings)

    assert {route.workflow for route in db_session.scalars(select(LLMWorkflowRoute))} == set(WORKFLOWS)
    for route in db_session.scalars(select(LLMWorkflowRoute)):
        deployment = db_session.get(LLMModelDeployment, route.deployment_id)
        provider = db_session.get(LLMProviderConfig, deployment.provider_config_id)
        assert provider.provider_type == "ZAI"
        assert not deployment.enabled
