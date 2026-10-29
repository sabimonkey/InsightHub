"""Per-workflow chat routing to model deployments. Embedding stays on its own provider."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.analysis import LLMModelDeployment, LLMProviderConfig, LLMWorkflowRoute
from app.services.llm.capability_probe import workflow_eligibility
from app.services.llm.deployments import deployment_route_ready, sync_deployments
from app.services.llm.registry import ProviderSpec, endpoint_configured, provider_specs, spec_from_deployment, sync_provider_rows

WORKFLOWS = ("EXTRACTION_AI", "ANALYSIS", "ASK_PLANNER", "ASK_ANSWER", "BRIEF")
STRUCTURED = {"EXTRACTION_AI", "ANALYSIS", "ASK_PLANNER", "BRIEF"}
LOCAL_TYPE = "LOCAL_OPENAI_COMPATIBLE"
RETIRED_PROVIDER_TYPES = {"LOCAL_OPENAI_COMPATIBLE", "DEEPSEEK", "SILICONFLOW", "GENERIC_OPENAI_COMPATIBLE"}


class RoutingError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _endpoint_specs(settings: Settings, session: Session | None = None) -> dict[str, ProviderSpec]:
    return {item.provider_type: item for item in provider_specs(settings, session)}


def _fake_allowed(settings: Settings) -> bool:
    return bool(
        settings.llm_enable_fake
        and settings.insighthub_system_scope == "AUTOMATION_TEST"
        and (settings.llm_default_provider or "").upper() == "FAKE"
    )


def _legacy_test_mode(settings: Settings) -> bool:
    return bool(settings.insighthub_system_scope == "AUTOMATION_TEST" and settings.llm_test_legacy_providers)


def _load_deployment(session: Session, deployment_id: uuid.UUID, settings: Settings | None = None) -> tuple[LLMModelDeployment, LLMProviderConfig, ProviderSpec]:
    settings = settings or get_settings()
    deployment = session.get(LLMModelDeployment, deployment_id)
    if deployment is None or deployment.archived_at is not None:
        raise RoutingError("DEPLOYMENT_NOT_FOUND", "找不到该模型部署。")
    provider = session.get(LLMProviderConfig, deployment.provider_config_id)
    if provider is None:
        raise RoutingError("PROVIDER_NOT_CONFIGURED", "找不到该模型提供方。")
    endpoints = _endpoint_specs(settings, session)
    endpoint = endpoints.get(provider.provider_type)
    if endpoint is None:
        raise RoutingError("PROVIDER_NOT_CONFIGURED", "找不到该模型提供方。")
    return deployment, provider, spec_from_deployment(provider, deployment, endpoint)


def list_routes(session: Session, settings: Settings) -> list[dict]:
    sync_deployments(session, settings)
    endpoints = _endpoint_specs(settings, session)
    result = []
    _ensure_routes(session, settings)
    for route in session.scalars(select(LLMWorkflowRoute).order_by(LLMWorkflowRoute.workflow.asc())):
        deployment, provider, spec = _load_deployment(session, route.deployment_id, settings)
        endpoint = endpoints[provider.provider_type]
        result.append(
            {
                "workflow": route.workflow,
                "deployment_id": str(deployment.id),
                "provider_type": provider.provider_type,
                "provider_name": provider.name,
                "deployment_display_name": deployment.display_name,
                "model": deployment.model_id,
                "label": f"{provider.name} / {deployment.display_name}",
                "is_local": provider.is_local,
                "configured": deployment_route_ready(deployment, provider, endpoint, settings, session),
                "credential_configured": endpoint_configured(endpoint, settings, session),
                "enabled": deployment.enabled and provider.enabled,
                "status": "CONFIGURATION_REQUIRED" if not endpoint_configured(endpoint, settings, session) else ("READY" if deployment.enabled and provider.enabled else "DISABLED"),
            }
        )
    return result


def list_route_options(session: Session, settings: Settings) -> list[dict]:
    sync_deployments(session, settings)
    endpoints = _endpoint_specs(settings, session)
    options = []
    for deployment in session.scalars(
        select(LLMModelDeployment)
        .where(LLMModelDeployment.archived_at.is_(None))
        .order_by(LLMModelDeployment.display_name.asc())
    ):
        provider = session.get(LLMProviderConfig, deployment.provider_config_id)
        if provider is None:
            continue
        if (deployment.capabilities_json or {}).get("supports_image_generation"):
            continue
        endpoint = endpoints.get(provider.provider_type)
        if endpoint is None:
            continue
        ready = deployment_route_ready(deployment, provider, endpoint, settings, session)
        options.append(
            {
                "deployment_id": str(deployment.id),
                "provider_type": provider.provider_type,
                "provider_name": provider.name,
                "deployment_display_name": deployment.display_name,
                "model": deployment.model_id,
                "label": f"{provider.name} / {deployment.display_name}",
                "is_local": provider.is_local,
                "configured": ready,
                "credential_configured": endpoint_configured(endpoint, settings, session),
                "enabled": deployment.enabled and provider.enabled,
                "status": "CONFIGURATION_REQUIRED" if not endpoint_configured(endpoint, settings, session) else ("READY" if ready else "DISABLED"),
                "capabilities": deployment.capabilities_json or {},
                "eligible_workflows": workflow_eligibility(deployment.capabilities_json),
            }
        )
    return options


def update_routes(session: Session, settings: Settings, mapping: dict[str, str]) -> list[dict]:
    unknown = set(mapping) - set(WORKFLOWS)
    if unknown or set(mapping) != set(WORKFLOWS):
        raise RoutingError("ROUTE_INVALID", "需要同时提交 Analysis、Ask Planner、Ask Answer 和 Brief 四条路由。")
    sync_deployments(session, settings)
    chosen: dict[str, uuid.UUID] = {}
    for workflow, raw in mapping.items():
        dep_id = _resolve_route_target(session, settings, raw)
        deployment, provider, spec = _load_deployment(session, dep_id, settings)
        endpoint = _endpoint_specs(settings, session)[provider.provider_type]
        _require_deployment(workflow, deployment, provider, spec, endpoint, settings, session)
        chosen[workflow] = dep_id
    now = datetime.now(timezone.utc)
    for workflow, dep_id in chosen.items():
        route = session.get(LLMWorkflowRoute, workflow)
        if route is None:
            route = LLMWorkflowRoute(workflow=workflow, deployment_id=dep_id, updated_at=now)
            session.add(route)
        else:
            route.deployment_id = dep_id
            route.updated_at = now
    session.commit()
    return list_routes(session, settings)


def set_provider_enabled(session: Session, settings: Settings, provider_id, enabled: bool) -> LLMProviderConfig:
    sync_provider_rows(session, settings)
    row = session.get(LLMProviderConfig, provider_id)
    if row is None:
        raise RoutingError("PROVIDER_NOT_CONFIGURED", "找不到该模型提供方。")
    if row.provider_type == LOCAL_TYPE and not enabled:
        raise RoutingError("LOCAL_PROVIDER_REQUIRED", "本地模型不能停用。")
    if not enabled:
        dep_ids = list(session.scalars(select(LLMModelDeployment.id).where(LLMModelDeployment.provider_config_id == row.id)))
        if dep_ids:
            used = list(session.scalars(select(LLMWorkflowRoute.workflow).where(LLMWorkflowRoute.deployment_id.in_(dep_ids))))
            if used:
                raise RoutingError("ROUTE_IN_USE", "请先把使用该模型的工作流改到其他部署。")
    row.enabled = enabled
    row.updated_at = datetime.now(timezone.utc)
    session.commit()
    return row


def resolve_workflow(session: Session, settings: Settings, workflow: str, override: str | None = None) -> ProviderSpec:
    if workflow not in WORKFLOWS:
        raise RoutingError("ROUTE_INVALID", "未知的工作流。")
    endpoints = _endpoint_specs(settings, session)
    explicit = (override or "").strip()
    if explicit:
        try:
            parsed = uuid.UUID(explicit)
        except ValueError:
            parsed = None
        if parsed is not None:
            deployment, provider, spec = _load_deployment(session, parsed, settings)
            endpoint = endpoints[provider.provider_type]
            _require_deployment(workflow, deployment, provider, spec, endpoint, settings, session)
            return spec
        if _fake_allowed(settings):
            fake = endpoints.get("FAKE")
            if fake is not None and fake.configured:
                return fake
        provider_type = explicit.upper()
        if provider_type in RETIRED_PROVIDER_TYPES and not _legacy_test_mode(settings):
            raise RoutingError("PROVIDER_RETIRED", "该模型提供方已退役，请在智谱 GLM 配置有效凭据后使用新路由。")
        sync_deployments(session, settings)
        deployment = _first_routable_deployment(session, settings, provider_type)
        if deployment is None:
            raise RoutingError("NOT_CONFIGURED", "所选模型提供方未配置可用部署。")
        provider = session.get(LLMProviderConfig, deployment.provider_config_id)
        endpoint = endpoints[provider.provider_type]
        spec = spec_from_deployment(provider, deployment, endpoint)
        _require_deployment(workflow, deployment, provider, spec, endpoint, settings, session)
        return spec
    if _fake_allowed(settings):
        fake = endpoints.get("FAKE")
        if fake is not None and fake.configured:
            return fake
    sync_deployments(session, settings)
    _ensure_routes(session, settings)
    route = session.get(LLMWorkflowRoute, workflow)
    if route is None:
        raise RoutingError("ROUTE_INVALID", "工作流路由未初始化。")
    deployment, provider, spec = _load_deployment(session, route.deployment_id, settings)
    endpoint = endpoints[provider.provider_type]
    if deployment_route_ready(deployment, provider, endpoint, settings, session):
        _check_capability(workflow, spec)
        return spec
    if _fake_allowed(settings):
        fake = endpoints.get("FAKE")
        if fake is not None and fake.configured:
            return fake
    if not endpoint_configured(endpoint, settings, session):
        raise RoutingError("CONFIGURATION_REQUIRED", "智谱 GLM API Key 尚未配置，请先在设置中保存并测试凭据。")
    if not provider.enabled or not deployment.enabled:
        raise RoutingError("PROVIDER_DISABLED", "所选模型部署已停用，请在模型卡中启用后再运行。")
    raise RoutingError("NOT_CONFIGURED", "所选模型部署未配置。")


def _ensure_routes(session: Session, settings: Settings) -> None:
    sync_deployments(session, settings)
    missing_workflows = [workflow for workflow in WORKFLOWS if session.get(LLMWorkflowRoute, workflow) is None]
    if not missing_workflows:
        return
    now = datetime.now(timezone.utc)
    from app.services.llm.cloud_defaults import CLOUD_DEFAULT_ROUTE_TARGETS, cloud_routes_configured, resolve_deployment_id

    if _legacy_test_mode(settings) and not cloud_routes_configured(settings):
        local = _first_routable_deployment(session, settings, LOCAL_TYPE)
        if local is None:
            local = session.scalar(select(LLMModelDeployment).join(LLMProviderConfig).where(LLMProviderConfig.provider_type == LOCAL_TYPE).limit(1))
        if local is None:
            return
        for workflow in missing_workflows:
            session.add(LLMWorkflowRoute(workflow=workflow, deployment_id=local.id, updated_at=now))
        session.commit()
        return

    for workflow in missing_workflows:
        provider_type, model_id = CLOUD_DEFAULT_ROUTE_TARGETS[workflow]
        dep_id = resolve_deployment_id(session, provider_type, model_id)
        if dep_id is None:
            return
        session.add(LLMWorkflowRoute(workflow=workflow, deployment_id=dep_id, updated_at=now))
    session.commit()


def _first_routable_deployment(session: Session, settings: Settings, provider_type: str) -> LLMModelDeployment | None:
    endpoints = _endpoint_specs(settings, session)
    endpoint = endpoints.get(provider_type)
    if endpoint is None:
        return None
    provider = session.scalar(select(LLMProviderConfig).where(LLMProviderConfig.provider_type == provider_type))
    if provider is None:
        return None
    for deployment in session.scalars(
        select(LLMModelDeployment)
        .where(
            LLMModelDeployment.provider_config_id == provider.id,
            LLMModelDeployment.enabled.is_(True),
            LLMModelDeployment.archived_at.is_(None),
        )
        .order_by(LLMModelDeployment.created_at.asc())
    ):
        if (deployment.capabilities_json or {}).get("supports_image_generation"):
            continue
        if deployment_route_ready(deployment, provider, endpoint, settings, session):
            return deployment
    return session.scalar(
        select(LLMModelDeployment)
        .where(LLMModelDeployment.provider_config_id == provider.id)
        .order_by(LLMModelDeployment.created_at.asc())
    )


def _resolve_route_target(session: Session, settings: Settings, raw: str) -> uuid.UUID:
    text = (raw or "").strip()
    try:
        return uuid.UUID(text)
    except ValueError:
        provider_type = text.upper()
        deployment = _first_routable_deployment(session, settings, provider_type)
        if deployment is not None:
            return deployment.id
        provider = session.scalar(select(LLMProviderConfig).where(LLMProviderConfig.provider_type == provider_type))
        if provider is None:
            raise RoutingError("PROVIDER_NOT_CONFIGURED", "找不到该模型提供方。")
        deployment = session.scalar(
            select(LLMModelDeployment)
            .where(LLMModelDeployment.provider_config_id == provider.id)
            .order_by(LLMModelDeployment.created_at.asc())
        )
        if deployment is None:
            raise RoutingError("NOT_CONFIGURED", "所选模型提供方未配置。")
        return deployment.id


def _require_deployment(
    workflow: str,
    deployment: LLMModelDeployment,
    provider: LLMProviderConfig,
    spec: ProviderSpec,
    endpoint: ProviderSpec,
    settings: Settings,
    session: Session,
) -> None:
    if (deployment.capabilities_json or {}).get("supports_image_generation"):
        raise RoutingError("IMAGE_MODEL_NOT_TEXT", "图像生成模型不能用于文本工作流。")
    if not endpoint_configured(endpoint, settings, session):
        raise RoutingError("CONFIGURATION_REQUIRED", "智谱 GLM API Key 尚未配置，请先在设置中保存并测试凭据。")
    if not provider.enabled or not deployment.enabled:
        raise RoutingError("PROVIDER_DISABLED", "所选模型部署已停用，请在模型卡中显式启用后再运行。")
    _check_capability(workflow, spec)


def _check_capability(workflow: str, spec: ProviderSpec) -> None:
    if workflow not in STRUCTURED:
        return
    capabilities = spec.capabilities or {}
    if capabilities.get("supports_json_schema") or capabilities.get("supports_json_object"):
        return
    raise RoutingError("STRUCTURED_OUTPUT_UNAVAILABLE", "该模型没有声明结构化输出，不能用于这个工作流。")
