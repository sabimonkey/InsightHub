"""Resolve cloud provider API keys: process env → vault → Settings (.env file).

MiniMax image generation is subscription-backed and deliberately resolves only
from the encrypted Vault in the production request path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.services.secrets.vault import CredentialVaultError, read_vault_secret


@dataclass(frozen=True)
class ResolvedApiKey:
    value: str
    source: str  # environment | vault | none


PROVIDER_ENV_NAMES: dict[str, str] = {
    "DEEPSEEK": "DEEPSEEK_API_KEY",
    "SILICONFLOW": "SILICONFLOW_API_KEY",
    "ZAI": "ZAI_API_KEY",
    "GENERIC_OPENAI_COMPATIBLE": "GENERIC_LLM_API_KEY",
    "MINIMAX_IMAGE": "MINIMAX_API_KEY",
}

CREDENTIAL_MANAGED_PROVIDER_TYPES = frozenset(PROVIDER_ENV_NAMES)


def settings_field_for_env(env_name: str, settings: Settings) -> str:
    mapping = {
        "DEEPSEEK_API_KEY": settings.deepseek_api_key,
        "SILICONFLOW_API_KEY": settings.siliconflow_api_key,
        "ZAI_API_KEY": settings.zai_api_key,
        "GENERIC_LLM_API_KEY": settings.generic_llm_api_key,
        "MINIMAX_API_KEY": settings.minimax_api_key,
    }
    return (mapping.get(env_name) or "").strip()


def resolve_api_key(
    provider_type: str,
    api_key_env: str | None,
    settings: Settings | None = None,
    session: Session | None = None,
) -> ResolvedApiKey:
    settings = settings or get_settings()
    env_name = api_key_env or PROVIDER_ENV_NAMES.get(provider_type)
    if not env_name:
        return ResolvedApiKey("", "none")

    proc = (os.environ.get(env_name) or "").strip()
    if proc:
        return ResolvedApiKey(proc, "environment")

    if session is not None:
        try:
            vaulted = read_vault_secret(session, provider_type)
        except CredentialVaultError:
            raise
        if vaulted:
            return ResolvedApiKey(vaulted.strip(), "vault")

    from_file = settings_field_for_env(env_name, settings)
    if from_file:
        return ResolvedApiKey(from_file, "environment")

    return ResolvedApiKey("", "none")


def credential_source_label(source: str) -> str:
    if source == "vault":
        return "页面安全存储"
    if source == "environment":
        return "环境变量"
    return "未配置"
