"""Auditable, database-backed global cover prompt revisions."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cover import CoverPromptRevision
from app.services.cover.prompt import DEFAULT_GLOBAL_PROMPT, GLOBAL_PROMPT_MAX_CHARS, GLOBAL_PROMPT_VERSION
from app.services.image.minimax_contract import normalize_prompt_text


def current_prompt_revision(session: Session) -> CoverPromptRevision:
    row = session.scalar(
        select(CoverPromptRevision).where(CoverPromptRevision.is_active.is_(True)).order_by(CoverPromptRevision.revision.desc())
    )
    if row is None:
        raise RuntimeError("Global cover prompt was not initialized by the database migration.")
    return row


def validate_global_prompt(prompt: str) -> str:
    normalized = normalize_prompt_text(prompt)
    if not normalized:
        raise ValueError("COVER_GLOBAL_PROMPT_REQUIRED")
    if len(normalized) > GLOBAL_PROMPT_MAX_CHARS:
        raise ValueError("COVER_GLOBAL_PROMPT_TOO_LONG")
    return normalized


def create_prompt_revision(session: Session, prompt: str, *, version: str = GLOBAL_PROMPT_VERSION) -> CoverPromptRevision:
    normalized = validate_global_prompt(prompt)
    # Serialize writers against the active revision; every prior version remains immutable.
    active = session.scalar(
        select(CoverPromptRevision).where(CoverPromptRevision.is_active.is_(True)).with_for_update()
    )
    next_revision = (active.revision if active else 0) + 1
    if active:
        active.is_active = False
        session.flush()
    row = CoverPromptRevision(revision=next_revision, prompt=normalized, version=version, is_active=True)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
