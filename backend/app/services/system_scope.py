"""Scope markers for automation vs daily-use data."""

from __future__ import annotations

import os

USER_SCOPE = "USER"
AUTOMATION_TEST_SCOPE = "AUTOMATION_TEST"

PROTECTED_CANONICAL_URLS = frozenset(
    {
        "https://x.com/ai_suxiaole/status/2106663866235261360",
        "https://x.com/denziideng/status/2106939914566922451",
        "https://x.com/bkdgiffug/status/2106962081182363902",
    }
)


def creation_scope_from_settings(settings) -> str:
    raw = (getattr(settings, "insighthub_system_scope", None) or os.environ.get("INSIGHTHUB_SYSTEM_SCOPE") or USER_SCOPE).strip().upper()
    if raw == AUTOMATION_TEST_SCOPE:
        return AUTOMATION_TEST_SCOPE
    return USER_SCOPE


def is_user_facing_scope(value: str | None) -> bool:
    return (value or USER_SCOPE) == USER_SCOPE


def user_scope_filter(column):
    from sqlalchemy import or_

    return or_(column == USER_SCOPE, column.is_(None))


def scope_visible_for_api(value: str | None, settings=None) -> bool:
    from app.core.config import get_settings

    settings = settings or get_settings()
    scope = (value or USER_SCOPE).strip().upper()
    active = creation_scope_from_settings(settings)
    if active == AUTOMATION_TEST_SCOPE:
        return scope == AUTOMATION_TEST_SCOPE
    return scope == USER_SCOPE


def api_visibility_filter(column, settings=None):
    """Daily-use API lists USER scope; automation servers list AUTOMATION_TEST only."""
    from app.core.config import get_settings

    settings = settings or get_settings()
    if creation_scope_from_settings(settings) == AUTOMATION_TEST_SCOPE:
        return column == AUTOMATION_TEST_SCOPE
    return user_scope_filter(column)


def canonical_url(value: str | None) -> str:
    if not value:
        return ""
    return value.split("?", 1)[0].rstrip("/")


def is_protected_source_url(original_url: str | None, canonical: str | None) -> bool:
    return any(canonical_url(value) in PROTECTED_CANONICAL_URLS for value in (original_url, canonical))


def looks_like_automation_marker(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.strip().lower()
    markers = ("e2e-", "e2e ", "playwright", "sandbox", "r1 closure smoke", "release smoke")
    return any(lowered.startswith("e2e-") or marker in lowered for marker in markers)
