"""Model deployment CRUD and bootstrap from legacy env model names."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.analysis import LLMModelDeployment, LLMProviderConfig, LLMWorkflowRoute
from app.services.llm.registry import ProviderSpec, endpoint_configured, provider_specs

LOCAL_TYPE = "LOCAL_OPENAI_COMPATIBLE"


def default_local_capabilities(settings: Settings) -> dict:
    return {
        "supports_json_schema": True,
        "supports_json_object": False,
        "supports_streaming": False,
        "supports_multimodal": False,
        "supports_reasoning": False,
        "context_window": settings.local_llm_context_window,
        "default_max_output_tokens": None,
        "timeout_seconds": None,
    }


def image_generation_capabilities() -> dict:
    return {
        "supports_image_generation": True,
        "supports_json_schema": False,
        "supports_json_object": False,
        "supports_streaming": False,
        "supports_multimodal": False,
        "supports_reasoning": False,
        "context_window": None,
        "default_max_output_tokens": None,
        "timeout_seconds": None,
    }


def conservative_cloud_capabilities() -> dict:
    return {
        "supports_json_schema": False,
        "supports_json_object": False,
        "supports_streaming": False,
        "supports_multimodal": False,
        "supports_reasoning": False,
        "context_window": None,
        "default_max_output_tokens": None,
        "timeout_seconds": None,
    }


def zai_capabilities() -> dict:
    return {
        "supports_json_schema": False,
        "supports_json_object": True,
        "supports_streaming": True,
        "supports_multimodal": True,
        "supports_vision": True,
        "supports_reasoning": True,
        "context_window": 1_000_000,
        "max_output_tokens": 128_000,
        "timeout_seconds": 180,
    }


def bootstrap_model_for_provider(row: LLMProviderConfig, settings: Settings, session: Session | None = None) -> str:
    legacy = (row.model or "").strip()
    if legacy:
        return legacy
    specs = {item.provider_type: item for item in provider_specs(settings, session)}
    spec = specs.get(row.provider_type)
    if spec is None:
        return ""
    return (spec.model or "").strip()


def sync_deployments(session: Session, settings: Settings | None = None) -> list[LLMModelDeployment]:
    settings = settings or get_settings()
    from app.services.llm.registry import sync_provider_rows

    sync_provider_rows(session, settings)
    specs = {item.provider_type: item for item in provider_specs(settings, session)}
    rows = list(session.scalars(select(LLMProviderConfig)))
    now = datetime.now(timezone.utc)
    created_any = False
    for row in rows:
        spec = specs.get(row.provider_type)
        if spec is None:
            continue
        active = list(session.scalars(select(LLMModelDeployment).where(
            LLMModelDeployment.provider_config_id == row.id,
            LLMModelDeployment.archived_at.is_(None),
        )))
        if row.provider_type == "ZAI" and spec is not None and not endpoint_configured(spec, settings, session):
            # No credential means the default GLM deployment cannot be scheduled.
            # Keep the row and its routes for setup, but require an explicit re-enable after key setup.
            for deployment in active:
                if deployment.enabled:
                    deployment.enabled = False
                    deployment.updated_at = now
                    created_any = True
        model_id = bootstrap_model_for_provider(row, settings, session)
        if not active and model_id and row.enabled:
            if row.provider_type == "MINIMAX_IMAGE":
                caps = image_generation_capabilities()
            elif row.provider_type == LOCAL_TYPE:
                caps = default_local_capabilities(settings)
            elif row.provider_type == "ZAI":
                caps = zai_capabilities()
            else:
                caps = {**conservative_cloud_capabilities(), **(row.capabilities_json or {})}
                if row.provider_type in {"DEEPSEEK", "GENERIC_OPENAI_COMPATIBLE"} and not caps.get("supports_json_schema"):
                    caps["supports_json_object"] = True
            session.add(
                LLMModelDeployment(
                    id=uuid.uuid4(),
                    provider_config_id=row.id,
                    display_name=model_id,
                    model_id=model_id,
                    enabled=True,
                    capabilities_json=caps,
                    created_at=now,
                    updated_at=now,
                )
            )
            created_any = True
        if row.provider_type == "ZAI":
            flashx = session.scalar(
                select(LLMModelDeployment).where(
                    LLMModelDeployment.provider_config_id == row.id,
                    LLMModelDeployment.model_id == "glm-5.3-flashx",
                )
            )
            if flashx is None:
                session.add(LLMModelDeployment(
                    id=uuid.uuid4(), provider_config_id=row.id,
                    display_name="GLM-5.3-FlashX", model_id="glm-5.3-flashx",
                    enabled=True, capabilities_json=zai_capabilities(),
                    created_at=now, updated_at=now,
                ))
                created_any = True
    if created_any:
        session.commit()
    return list(session.scalars(select(LLMModelDeployment)))


def deployment_route_ready(
    deployment: LLMModelDeployment,
    provider: LLMProviderConfig,
    spec: ProviderSpec,
    settings=None,
    session: Session | None = None,
) -> bool:
    from app.core.config import get_settings

    settings = settings or get_settings()
    if not deployment.enabled or not provider.enabled:
        return False
    return endpoint_configured(spec, settings, session)


def list_deployments_for_provider(session: Session, provider_id: uuid.UUID) -> list[LLMModelDeployment]:
    return list(
        session.scalars(
            select(LLMModelDeployment)
            .where(LLMModelDeployment.provider_config_id == provider_id, LLMModelDeployment.archived_at.is_(None))
            .order_by(LLMModelDeployment.display_name.asc())
        )
    )


def archive_deployment(session: Session, deployment_id: uuid.UUID) -> LLMModelDeployment:
    row = session.get(LLMModelDeployment, deployment_id)
    if row is None:
        raise ValueError("DEPLOYMENT_NOT_FOUND")
    if row.archived_at is not None:
        return row
    used = routes_using_deployment(session, row.id)
    if used:
        raise ValueError("ROUTE_IN_USE")
    now = datetime.now(timezone.utc)
    row.enabled = False
    row.archived_at = now
    row.updated_at = now
    caps = dict(row.capabilities_json or {})
    caps["archived"] = True
    row.capabilities_json = caps
    session.commit()
    return row


def routes_using_deployment(session: Session, deployment_id: uuid.UUID) -> list[str]:
    return list(session.scalars(select(LLMWorkflowRoute.workflow).where(LLMWorkflowRoute.deployment_id == deployment_id)))


def create_deployment(
    session: Session,
    provider_id: uuid.UUID,
    *,
    display_name: str,
    model_id: str,
    capabilities: dict | None = None,
    enabled: bool = True,
) -> LLMModelDeployment:
    provider = session.get(LLMProviderConfig, provider_id)
    if provider is None:
        raise ValueError("PROVIDER_NOT_CONFIGURED")
    model_id = (model_id or "").strip()
    display_name = (display_name or "").strip() or model_id
    if not model_id:
        raise ValueError("MODEL_ID_REQUIRED")
    now = datetime.now(timezone.utc)
    if provider.provider_type == "MINIMAX_IMAGE":
        caps = capabilities if capabilities is not None else image_generation_capabilities()
    else:
        caps = capabilities if capabilities is not None else conservative_cloud_capabilities()
    if provider.provider_type == LOCAL_TYPE:
        caps = {**default_local_capabilities(get_settings()), **caps}
    row = LLMModelDeployment(
        id=uuid.uuid4(),
        provider_config_id=provider.id,
        display_name=display_name,
        model_id=model_id,
        enabled=enabled,
        capabilities_json=caps,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.commit()
    return row


def update_deployment(session: Session, deployment_id: uuid.UUID, **fields) -> LLMModelDeployment:
    row = session.get(LLMModelDeployment, deployment_id)
    if row is None:
        raise ValueError("DEPLOYMENT_NOT_FOUND")
    if "display_name" in fields and fields["display_name"]:
        row.display_name = str(fields["display_name"]).strip()
    if "model_id" in fields and fields["model_id"]:
        row.model_id = str(fields["model_id"]).strip()
    if "enabled" in fields:
        enabled = bool(fields["enabled"])
        if not enabled:
            used = routes_using_deployment(session, row.id)
            if used:
                raise ValueError("ROUTE_IN_USE")
        row.enabled = enabled
    if "capabilities" in fields and fields["capabilities"] is not None:
        row.capabilities_json = {**(row.capabilities_json or {}), **dict(fields["capabilities"])}
    row.updated_at = datetime.now(timezone.utc)
    session.commit()
    return row
