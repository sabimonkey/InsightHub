"""Deployment capability audit for benchmark report."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.analysis import LLMModelDeployment, LLMProviderConfig
from app.services.llm.registry import build_provider, spec_from_deployment, provider_specs


def audit_providers(session: Session, settings: Settings) -> list[dict]:
    endpoints = {item.provider_type: item for item in provider_specs(settings)}
    rows = []
    for deployment in session.scalars(select(LLMModelDeployment).order_by(LLMModelDeployment.display_name.asc())):
        provider = session.get(LLMProviderConfig, deployment.provider_config_id)
        if provider is None:
            continue
        if provider.provider_type not in {"DEEPSEEK", "SILICONFLOW"}:
            continue
        endpoint = endpoints.get(provider.provider_type)
        spec = spec_from_deployment(provider, deployment, endpoint) if endpoint else None
        caps = deployment.capabilities_json or {}
        built = build_provider(spec, settings) if spec and endpoint else None
        rows.append(
            {
                "deployment_id": str(deployment.id),
                "provider_type": provider.provider_type,
                "display_name": deployment.display_name,
                "model_id": deployment.model_id,
                "capabilities_json": caps,
                "resolved_context_window": getattr(built, "context_window", None) if built else None,
                "timeout_seconds": caps.get("timeout_seconds") or settings.llm_timeout_seconds,
            }
        )
    return rows
