"""Helpers for llm routing tests — isolated from user provider enabled state."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.analysis import LLMModelDeployment, LLMProviderConfig
from app.services.llm.deployments import sync_deployments
from app.services.llm.registry import sync_provider_rows


def ensure_deployment_enabled(session: Session, settings: Settings, provider_type: str) -> LLMModelDeployment:
    """Enable provider + first deployment for tests that must route to this type."""
    sync_provider_rows(session, settings)
    provider = session.scalar(select(LLMProviderConfig).where(LLMProviderConfig.provider_type == provider_type))
    if provider is None:
        raise AssertionError(f"missing provider {provider_type}")
    provider.enabled = True
    session.flush()
    sync_deployments(session, settings)
    deployment = session.scalar(
        select(LLMModelDeployment)
        .where(LLMModelDeployment.provider_config_id == provider.id, LLMModelDeployment.archived_at.is_(None))
        .order_by(LLMModelDeployment.created_at.asc())
    )
    if deployment is None:
        raise AssertionError(f"missing deployment for {provider_type}")
    deployment.enabled = True
    session.commit()
    return deployment


def ensure_deployment_disabled(session: Session, settings: Settings, provider_type: str) -> LLMModelDeployment:
    sync_provider_rows(session, settings)
    provider = session.scalar(select(LLMProviderConfig).where(LLMProviderConfig.provider_type == provider_type))
    assert provider is not None
    provider.enabled = True
    session.flush()
    sync_deployments(session, settings)
    deployment = session.scalar(
        select(LLMModelDeployment)
        .where(LLMModelDeployment.provider_config_id == provider.id, LLMModelDeployment.archived_at.is_(None))
        .order_by(LLMModelDeployment.created_at.asc())
    )
    assert deployment is not None
    deployment.enabled = False
    session.commit()
    return deployment
