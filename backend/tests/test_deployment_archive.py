import uuid

import pytest
from sqlalchemy import select

from app.models.analysis import LLMModelDeployment, LLMProviderConfig, LLMWorkflowRoute
from app.services.llm.deployments import archive_deployment, create_deployment, routes_using_deployment, sync_deployments


@pytest.fixture
def siliconflow_provider(db_session, monkeypatch):
    monkeypatch.setenv("SILICONFLOW_API_KEY", "test-key")
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    sync_deployments(db_session, settings)
    return db_session.scalar(select(LLMProviderConfig).where(LLMProviderConfig.provider_type == "SILICONFLOW"))


def test_archive_blocked_when_route_in_use(db_session, siliconflow_provider):
    dep = create_deployment(
        db_session,
        siliconflow_provider.id,
        display_name="Route Test",
        model_id="test/route-model",
    )
    route = db_session.get(LLMWorkflowRoute, "BRIEF")
    assert route is not None
    original = route.deployment_id
    route.deployment_id = dep.id
    db_session.commit()
    try:
        with pytest.raises(ValueError, match="ROUTE_IN_USE"):
            archive_deployment(db_session, dep.id)
    finally:
        route.deployment_id = original
        db_session.commit()


def test_archive_succeeds_without_routes(db_session, siliconflow_provider):
    dep = create_deployment(
        db_session,
        siliconflow_provider.id,
        display_name="Orphan",
        model_id="deepseek-ai/DeepSeek-V4.1-Flash",
    )
    archived = archive_deployment(db_session, dep.id)
    assert archived.archived_at is not None
    assert archived.enabled is False
    assert (archived.capabilities_json or {}).get("archived") is True
    listed = list(
        db_session.scalars(
            select(LLMModelDeployment).where(
                LLMModelDeployment.provider_config_id == siliconflow_provider.id,
                LLMModelDeployment.archived_at.is_(None),
            )
        )
    )
    assert all(row.model_id != "deepseek-ai/DeepSeek-V4.1-Flash" for row in listed)


def test_archive_idempotent(db_session, siliconflow_provider):
    dep = create_deployment(db_session, siliconflow_provider.id, display_name="Once", model_id="once-model")
    first = archive_deployment(db_session, dep.id)
    second = archive_deployment(db_session, dep.id)
    assert first.id == second.id
    assert second.archived_at is not None


def test_routes_using_deployment_lists_workflows(db_session, siliconflow_provider):
    dep = create_deployment(db_session, siliconflow_provider.id, display_name="Used", model_id="used-model")
    route = db_session.get(LLMWorkflowRoute, "BRIEF")
    assert route is not None
    original = route.deployment_id
    route.deployment_id = dep.id
    db_session.commit()
    try:
        assert routes_using_deployment(db_session, dep.id) == ["BRIEF"]
    finally:
        route.deployment_id = original
        db_session.commit()
