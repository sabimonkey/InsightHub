"""Conservative monthly MiniMax run accounting and serialization lock."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.analysis import LLMProviderConfig
from app.models.cover import CoverGenerationRun
from app.models.source_item import SourceItem
from app.services.system_scope import USER_SCOPE


def monthly_budget_usage_count(session: Session) -> int:
    """Count committed USER generation attempts, including failures and reservations."""
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return int(
        session.scalar(
            select(func.count())
            .select_from(CoverGenerationRun)
            .join(SourceItem, SourceItem.id == CoverGenerationRun.source_item_id)
            .where(SourceItem.system_scope == USER_SCOPE)
            .where(CoverGenerationRun.created_at >= start)
        )
        or 0
    )


def lock_monthly_budget(session: Session, provider_id, *, settings: Settings | None = None) -> tuple[int, int]:
    """Lock the provider row until the caller commits the newly reserved run."""
    from app.services.cover.settings_prefs import load_cover_prefs

    provider = session.scalar(
        select(LLMProviderConfig).where(LLMProviderConfig.id == provider_id).with_for_update()
    )
    if provider is None:
        raise LookupError("MINIMAX_PROVIDER_NOT_FOUND")
    prefs = load_cover_prefs(session, settings or get_settings())
    used = monthly_budget_usage_count(session)
    return used, prefs.monthly_budget
