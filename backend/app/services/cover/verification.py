"""Verify persisted cover assets (file + DB linkage)."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.cover import CoverGenerationRun, SourceCoverAsset
from app.services.cover.storage import CoverStorageError, read_cover_file


def verify_asset_file(relative_path: str) -> tuple[bool, str | None]:
    try:
        data, _media = read_cover_file(relative_path)
    except CoverStorageError as exc:
        return False, exc.code
    except OSError:
        return False, "COVER_STORAGE_FAILED"
    if len(data) < 32:
        return False, "COVER_OUTPUT_MISSING"
    return True, None


def verify_generated_cover_for_source(
    session: Session,
    source_id: uuid.UUID,
    *,
    asset: SourceCoverAsset | None = None,
) -> tuple[bool, str | None, SourceCoverAsset | None]:
    if asset is None:
        from sqlalchemy import select

        asset = session.scalar(
            select(SourceCoverAsset).where(
                SourceCoverAsset.source_item_id == source_id,
                SourceCoverAsset.is_current.is_(True),
                SourceCoverAsset.kind == "GENERATED",
            )
        )
    if asset is None:
        return False, "COVER_OUTPUT_MISSING", None
    if asset.source_item_id != source_id:
        return False, "COVER_SOURCE_LINK_FAILED", asset
    ok, code = verify_asset_file(asset.relative_path)
    if not ok:
        return False, code or "COVER_ASSET_UNAVAILABLE", asset
    return True, None, asset


def effective_run_success(session: Session, run: CoverGenerationRun | None) -> tuple[bool, str | None]:
    if run is None:
        return False, "COVER_STATUS_UNKNOWN"
    if run.status in {"QUEUED", "GENERATING", "DECODING", "VALIDATING", "SAVING"}:
        return False, None
    if run.status == "FAILED":
        return False, run.error_code or "COVER_PROVIDER_FAILED"
    if run.status != "SUCCEEDED":
        return False, "COVER_STATUS_UNKNOWN"
    if run.asset_id is None:
        return False, "COVER_PERSISTENCE_FAILED"
    asset = session.get(SourceCoverAsset, run.asset_id)
    if asset is None:
        return False, "COVER_PERSISTENCE_FAILED"
    ok, code, _ = verify_generated_cover_for_source(session, run.source_item_id, asset=asset)
    if not ok:
        return False, code or "COVER_ASSET_UNAVAILABLE"
    return True, None
