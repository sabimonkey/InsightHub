"""Default cloud workflow routing for PILOT-03B cutover (persisted in llm_workflow_routes)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.analysis import LLMModelDeployment, LLMProviderConfig, LLMWorkflowRoute
from app.services.llm.deployments import sync_deployments
from app.services.llm.registry import endpoint_configured, provider_specs

# workflow -> (provider_type, preferred model_id)
GLM_FLASH_MODEL = "glm-5.3-flash"
GLM_FLASHX_MODEL = "glm-5.3-flashx"
GLM_PROVIDER = "ZAI"

CLOUD_DEFAULT_ROUTE_TARGETS: dict[str, tuple[str, str]] = {
    "EXTRACTION_AI": (GLM_PROVIDER, GLM_FLASHX_MODEL),
    "ANALYSIS": (GLM_PROVIDER, GLM_FLASH_MODEL),
    "ASK_ANSWER": (GLM_PROVIDER, GLM_FLASH_MODEL),
    "BRIEF": (GLM_PROVIDER, GLM_FLASH_MODEL),
    "ASK_PLANNER": (GLM_PROVIDER, GLM_FLASH_MODEL),
}


def resolve_deployment_id(session: Session, provider_type: str, model_id: str) -> uuid.UUID | None:
    row = session.scalar(
        select(LLMModelDeployment.id)
        .join(LLMProviderConfig, LLMProviderConfig.id == LLMModelDeployment.provider_config_id)
        .where(LLMProviderConfig.provider_type == provider_type, LLMModelDeployment.model_id == model_id)
        .limit(1)
    )
    if row is not None:
        return row
    return session.scalar(
        select(LLMModelDeployment.id)
        .join(LLMProviderConfig, LLMProviderConfig.id == LLMModelDeployment.provider_config_id)
        .where(LLMProviderConfig.provider_type == provider_type)
        .order_by(LLMModelDeployment.created_at.asc())
        .limit(1)
    )


def cloud_routes_configured(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    specs = {item.provider_type: item for item in provider_specs(settings)}
    for provider_type in {v[0] for v in CLOUD_DEFAULT_ROUTE_TARGETS.values()}:
        spec = specs.get(provider_type)
        if spec is None or not endpoint_configured(spec, settings):
            return False
    return True


def apply_cloud_default_routes(session: Session, settings: Settings | None = None) -> list[dict]:
    settings = settings or get_settings()
    if not cloud_routes_configured(settings):
        raise RuntimeError("CLOUD_ROUTE_TARGETS_NOT_CONFIGURED")
    sync_deployments(session, settings)
    now = datetime.now(timezone.utc)
    for workflow, (provider_type, model_id) in CLOUD_DEFAULT_ROUTE_TARGETS.items():
        dep_id = resolve_deployment_id(session, provider_type, model_id)
        if dep_id is None:
            raise RuntimeError(f"DEPLOYMENT_NOT_FOUND:{workflow}:{provider_type}:{model_id}")
        route = session.get(LLMWorkflowRoute, workflow)
        if route is None:
            session.add(LLMWorkflowRoute(workflow=workflow, deployment_id=dep_id, updated_at=now))
        else:
            route.deployment_id = dep_id
            route.updated_at = now
    session.commit()
    from app.services.llm.routing import list_routes

    return list_routes(session, settings)
