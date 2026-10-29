"""Persisted cover automation preferences (MINIMAX provider capabilities + env fallback)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.analysis import LLMProviderConfig

CAP_KEY = "cover_automation"
MIN_COVER_MONTHLY_BUDGET = 1
MAX_COVER_MONTHLY_BUDGET = 500


@dataclass(frozen=True)
class CoverAutomationPrefs:
    auto_enabled: bool
    requires_analysis: bool
    monthly_budget: int


def _provider_row(session: Session) -> LLMProviderConfig | None:
    return session.scalar(select(LLMProviderConfig).where(LLMProviderConfig.provider_type == "MINIMAX_IMAGE"))


def load_cover_prefs(session: Session, settings: Settings | None = None) -> CoverAutomationPrefs:
    settings = settings or get_settings()
    row = _provider_row(session)
    blob = dict(row.capabilities_json or {}) if row else {}
    nested = blob.get(CAP_KEY) if isinstance(blob.get(CAP_KEY), dict) else {}
    auto = nested.get("auto_enabled")
    if auto is None:
        auto = settings.cover_auto_enabled
    requires = nested.get("requires_analysis")
    if requires is None:
        requires = settings.cover_auto_requires_analysis
    budget = nested.get("monthly_budget")
    if budget is None:
        budget = settings.cover_monthly_budget
    return CoverAutomationPrefs(
        auto_enabled=bool(auto),
        requires_analysis=bool(requires),
        monthly_budget=int(budget),
    )


def save_cover_auto_enabled(session: Session, enabled: bool) -> CoverAutomationPrefs:
    row = _provider_row(session)
    if row is None:
        raise ValueError("MINIMAX_IMAGE provider not configured")
    caps = dict(row.capabilities_json or {})
    nested = dict(caps.get(CAP_KEY) or {}) if isinstance(caps.get(CAP_KEY), dict) else {}
    nested["auto_enabled"] = bool(enabled)
    caps[CAP_KEY] = nested
    row.capabilities_json = caps
    session.add(row)
    session.commit()
    return load_cover_prefs(session)


def save_cover_monthly_budget(session: Session, monthly_budget: int) -> CoverAutomationPrefs:
    if not MIN_COVER_MONTHLY_BUDGET <= monthly_budget <= MAX_COVER_MONTHLY_BUDGET:
        raise ValueError("MONTHLY_BUDGET_OUT_OF_RANGE")
    row = _provider_row(session)
    if row is None:
        raise ValueError("PROVIDER_NOT_CONFIGURED")
    caps = dict(row.capabilities_json or {})
    nested = dict(caps.get(CAP_KEY) or {}) if isinstance(caps.get(CAP_KEY), dict) else {}
    nested["monthly_budget"] = monthly_budget
    caps[CAP_KEY] = nested
    row.capabilities_json = caps
    session.add(row)
    session.commit()
    return load_cover_prefs(session)
