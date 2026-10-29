import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.services.llm.credential_resolver import resolve_api_key
from app.models.analysis import LLMModelDeployment, LLMProviderConfig
from app.services.llm.provider import (
    DeepSeekProvider,
    FakeLLMProvider,
    GenericOpenAICompatibleProvider,
    LocalOpenAICompatibleProvider,
    SiliconFlowProvider,
    ZaiProvider,
    is_local_base_url,
)
from app.services.llm.types import LLMError


@dataclass
class ProviderSpec:
    provider_type: str
    name: str
    base_url: str
    model: str
    is_local: bool
    api_key_env: str | None
    configured: bool
    capabilities: dict
    deployment_id: uuid.UUID | None = None
    provider_config_id: uuid.UUID | None = None
    deployment_display_name: str | None = None


def endpoint_configured(spec: ProviderSpec, settings: Settings | None = None, session: Session | None = None) -> bool:
    settings = settings or get_settings()
    if spec.provider_type == "FAKE":
        return spec.configured
    if spec.api_key_env is None:
        key_ready = True
    else:
        try:
            key_ready = bool(resolve_api_key(spec.provider_type, spec.api_key_env, settings, session).value)
        except Exception:
            key_ready = False
    if spec.is_local:
        return bool(spec.base_url and is_local_base_url(spec.base_url) and key_ready)
    return bool(spec.base_url and key_ready)


def provider_specs(settings: Settings | None = None, session: Session | None = None) -> list[ProviderSpec]:
    settings = settings or get_settings()
    specs = [
        _endpoint("ZAI", "智谱 GLM", settings.zai_base_url, settings.zai_model, "ZAI_API_KEY", local=False, settings=settings, session=session),
        _minimax_image(settings, session),
    ]
    # Legacy transports are available only to isolated AUTOMATION_TEST fixtures.
    # They are never registered or seeded by the production USER runtime.
    if settings.insighthub_system_scope == "AUTOMATION_TEST" and settings.llm_test_legacy_providers:
        specs.extend(
            [
                _endpoint("LOCAL_OPENAI_COMPATIBLE", "LM Studio", settings.lmstudio_base_url, settings.lmstudio_model, None, local=True, settings=settings, session=session),
                _endpoint("DEEPSEEK", "DeepSeek", settings.deepseek_base_url, settings.deepseek_model, "DEEPSEEK_API_KEY", local=False, settings=settings, session=session),
                _endpoint("SILICONFLOW", "SiliconFlow", settings.siliconflow_base_url, settings.siliconflow_model, "SILICONFLOW_API_KEY", local=False, settings=settings, session=session),
                _endpoint("GENERIC_OPENAI_COMPATIBLE", "Generic", settings.generic_llm_base_url, settings.generic_llm_model, "GENERIC_LLM_API_KEY", local=False, settings=settings, session=session),
            ]
        )
    if settings.llm_enable_fake:
        specs.append(
            ProviderSpec(
                "FAKE",
                "Fake",
                "http://127.0.0.1/fake",
                "fake-model",
                True,
                None,
                True,
                {"supports_json_object": True, "supports_json_schema": False, "supports_vision": False, "supports_streaming": True, "context_window": None, "max_output_tokens": None},
            )
        )
    default = (settings.llm_default_provider or "").upper()
    ordered = sorted(specs, key=lambda item: (item.provider_type != default, not endpoint_configured(item, settings, session)))
    return ordered


def _minimax_image(settings: Settings, session: Session | None = None) -> ProviderSpec:
    key_ready = bool(resolve_api_key("MINIMAX_IMAGE", "MINIMAX_API_KEY", settings, session).value)
    configured = bool(settings.minimax_base_url and key_ready)
    return ProviderSpec(
        "MINIMAX_IMAGE",
        "MiniMax",
        settings.minimax_base_url or "",
        settings.minimax_image_model or "image-01",
        False,
        "MINIMAX_API_KEY",
        configured,
        {"supports_image_generation": True},
    )


def _endpoint(
    provider_type: str,
    name: str,
    base_url: str,
    model: str,
    env_name: str | None,
    local: bool,
    *,
    settings: Settings,
    session: Session | None,
) -> ProviderSpec:
    key_ready = True if env_name is None else bool(resolve_api_key(provider_type, env_name, settings, session).value)
    local_ok = is_local_base_url(base_url) if local else False
    is_local = local and local_ok
    configured = bool(base_url and key_ready and (local_ok if local else True))
    return ProviderSpec(
        provider_type,
        name,
        base_url or "",
        model or "",
        is_local,
        env_name,
        configured,
        {},
    )


def spec_from_deployment(provider: LLMProviderConfig, deployment: LLMModelDeployment, endpoint: ProviderSpec) -> ProviderSpec:
    caps = dict(deployment.capabilities_json or {})
    return ProviderSpec(
        provider_type=provider.provider_type,
        name=provider.name,
        base_url=provider.base_url,
        model=deployment.model_id,
        is_local=provider.is_local,
        api_key_env=provider.api_key_env,
        configured=endpoint_configured(endpoint, get_settings(), None),
        capabilities=caps,
        deployment_id=deployment.id,
        provider_config_id=provider.id,
        deployment_display_name=deployment.display_name,
    )


def sync_provider_rows(session: Session, settings: Settings | None = None) -> list[LLMProviderConfig]:
    settings = settings or get_settings()
    specs = provider_specs(settings, session)
    default_type = next(
        (
            item.provider_type
            for item in specs
            if not item.capabilities.get("supports_image_generation")
            and item.provider_type != "FAKE"
            and endpoint_configured(item, settings, session)
        ),
        "",
    )
    if settings.llm_default_provider:
        wanted = settings.llm_default_provider.upper()
        if wanted != "FAKE" and any(
            item.provider_type == wanted
            and not item.capabilities.get("supports_image_generation")
            and endpoint_configured(item, settings, session)
            for item in specs
        ):
            default_type = wanted
    rows: list[LLMProviderConfig] = []
    now = datetime.now(timezone.utc)
    for spec in specs:
        row = session.scalar(select(LLMProviderConfig).where(LLMProviderConfig.provider_type == spec.provider_type))
        created = row is None
        if created:
            row = LLMProviderConfig(id=uuid.uuid4(), provider_type=spec.provider_type, model=spec.model or "", created_at=now)
            session.add(row)
        row.name = spec.name
        row.base_url = spec.base_url
        row.is_local = spec.is_local
        if created:
            row.enabled = True
            row.capabilities_json = {}
        if spec.model and not row.model:
            row.model = spec.model
        elif spec.model and row.provider_type in {"LOCAL_OPENAI_COMPATIBLE"}:
            row.model = spec.model
        row.api_key_env = spec.api_key_env
        row.is_default = spec.provider_type == default_type
        row.updated_at = now
        rows.append(row)
    session.commit()
    return rows


def build_provider(
    spec: ProviderSpec,
    settings: Settings | None = None,
    client=None,
    fake: FakeLLMProvider | None = None,
    session: Session | None = None,
):
    settings = settings or get_settings()
    if spec.provider_type == "FAKE":
        return fake or FakeLLMProvider()
    key = ""
    if spec.api_key_env:
        key = resolve_api_key(spec.provider_type, spec.api_key_env, settings, session).value
    timeout = spec.capabilities.get("timeout_seconds") or settings.llm_timeout_seconds
    common = {
        "base_url": spec.base_url,
        "model": spec.model,
        "api_key": key,
        "timeout": timeout,
        "max_retries": settings.llm_max_retries,
        "supports_json_schema": bool(spec.capabilities.get("supports_json_schema")),
        "supports_json_object": bool(spec.capabilities.get("supports_json_object", True)),
        "client": client,
    }
    if spec.provider_type == "LOCAL_OPENAI_COMPATIBLE":
        provider = LocalOpenAICompatibleProvider(**common)
    elif spec.provider_type == "DEEPSEEK":
        provider = DeepSeekProvider(**common)
    elif spec.provider_type == "SILICONFLOW":
        provider = SiliconFlowProvider(**common)
    elif spec.provider_type == "ZAI":
        provider = ZaiProvider(**common)
    elif spec.provider_type == "GENERIC_OPENAI_COMPATIBLE":
        provider = GenericOpenAICompatibleProvider(**common)
    else:
        raise LLMError("PROVIDER_NOT_CONFIGURED", "未知的模型提供方。")
    from app.services.analysis.budget import lookup_model_pricing

    window = spec.capabilities.get("context_window")
    pricing = lookup_model_pricing(spec.provider_type, spec.model)
    if not window and pricing:
        window = pricing.context_tokens
    if not window and spec.provider_type == "DEEPSEEK":
        # deepseek-v4-pro accepts a 1M context. The 8k default made real briefs look over budget.
        window = 1_000_000
    provider.context_window = window or settings.default_llm_context_window
    max_out = spec.capabilities.get("max_output_tokens") or spec.capabilities.get("default_max_output_tokens")
    if not max_out and pricing:
        max_out = pricing.max_output_tokens
    provider.max_output_tokens = int(max_out) if max_out else settings.analysis_max_output_tokens
    provider.supports_streaming = bool(spec.capabilities.get("supports_streaming"))
    if spec.provider_type == "FAKE":
        provider.supports_streaming = True
    return provider
