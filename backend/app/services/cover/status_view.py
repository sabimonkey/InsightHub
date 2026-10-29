"""Authoritative cover task + display status for API and UI."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cover import CoverGenerationRun, SourceCoverAsset
from app.models.extraction import ExtractedDocument
from app.models.source_item import SourceItem
from app.services.cover.resolution import resolve_cover
from app.services.cover.service import ACTIVE_STATUSES, CoverGenerationService
from app.services.cover.verification import effective_run_success


def build_cover_status_payload(
    session: Session,
    source_id: uuid.UUID,
    *,
    run: CoverGenerationRun | None,
) -> dict:
    doc = session.scalar(
        select(ExtractedDocument).where(ExtractedDocument.source_item_id == source_id).order_by(ExtractedDocument.created_at.desc())
    )
    service = CoverGenerationService(session)
    if run is None:
        run = service.latest_run(source_id)
    resolved = resolve_cover(session, source_id, doc)
    if run is None:
        return {
            "ok": True,
            "status": "NONE",
            "stage": "NONE",
            "lifecycle": "idle",
            "display_ready": resolved is not None,
            "terminal_success": False,
            "has_generated_cover": service.current_generated_asset(source_id) is not None,
            "cover_url": f"/api/sources/{source_id}/cover-image" if resolved else None,
            "current_cover_url": f"/api/sources/{source_id}/cover-image" if resolved else None,
            "candidate_asset_id": None,
            "candidate_cover_url": None,
            "candidate_is_current": False,
            "candidate_review_state": None,
            "cover_origin": resolved.kind if resolved else None,
        }

    terminal_ok, effective_err = effective_run_success(session, run)
    if run.status in ACTIVE_STATUSES:
        lifecycle = "running"
    elif terminal_ok:
        lifecycle = "succeeded"
    else:
        lifecycle = "failed"

    current_asset = service.current_generated_asset(source_id)
    version = str(current_asset.id) if current_asset else str(int(run.updated_at.timestamp())) if run.updated_at else "0"
    show_image = resolved is not None
    cover_url = f"/api/sources/{source_id}/cover-image?v={version}" if show_image else None
    candidate = session.get(SourceCoverAsset, run.asset_id) if run.asset_id else None
    candidate_ready = bool(
        terminal_ok
        and candidate is not None
        and candidate.source_item_id == source_id
        and candidate.kind == "GENERATED"
        and candidate.generation_run_id == run.id
    )
    candidate_url = (
        f"/api/sources/{source_id}/cover-image?asset_id={candidate.id}"
        if candidate_ready and candidate is not None
        else None
    )

    return {
        "ok": True,
        "run_id": str(run.id),
        "status": run.status,
        "stage": run.stage,
        "lifecycle": lifecycle,
        "display_ready": show_image,
        "terminal_success": terminal_ok,
        "error_code": (run.error_code or effective_err) if lifecycle == "failed" else None,
        "error_message": run.error_message if lifecycle == "failed" else None,
        "has_generated_cover": service.current_generated_asset(source_id) is not None,
        "cover_url": cover_url,
        "current_cover_url": cover_url,
        "candidate_asset_id": str(candidate.id) if candidate_ready and candidate is not None else None,
        "candidate_cover_url": candidate_url,
        "candidate_is_current": bool(candidate_ready and candidate is not None and candidate.is_current),
        "candidate_review_state": run.candidate_review_state,
        "cover_origin": resolved.kind if resolved else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }
