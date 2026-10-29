from app.core.config import Settings
from app.services.llm.registry import ProviderSpec, endpoint_configured, provider_specs

RETRYABLE = {"PROVIDER_UNAVAILABLE", "PROVIDER_OVERLOADED", "TIMEOUT", "RATE_LIMITED"}
NEVER_FALLBACK_TO = {"FAKE", "LOCAL_OPENAI_COMPATIBLE", "DEEPSEEK", "SILICONFLOW", "GENERIC_OPENAI_COMPATIBLE"}


def select_fallback(settings: Settings, requested_type: str, privacy_level: str) -> ProviderSpec | None:
    if not settings.llm_provider_fallback_enabled:
        return None
    name = (settings.llm_fallback_provider or "").strip()
    if not name or name == requested_type or name.upper() == "FAKE":
        return None
    legacy = name.upper() in NEVER_FALLBACK_TO
    if legacy and not (settings.insighthub_system_scope == "AUTOMATION_TEST" and settings.llm_test_legacy_providers):
        return None
    spec = next((item for item in provider_specs(settings) if item.provider_type == name and endpoint_configured(item)), None)
    if spec is None:
        return None
    if privacy_level == "SENSITIVE" and not spec.is_local:
        return None
    requested = next((item for item in provider_specs(settings) if item.provider_type == requested_type), None)
    if requested is not None and requested.is_local and not spec.is_local:
        return None
    return spec
