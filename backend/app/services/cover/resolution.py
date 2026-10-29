"""Cover display priority: USER asset → source og → generated asset."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cover import SourceCoverAsset
from app.models.extraction import ExtractedDocument
from app.services.library_preview import preview_image_from_document


@dataclass
class ResolvedCover:
    kind: str  # user | source | generated
    relative_path: str | None = None
    remote_url: str | None = None


def _current_asset(session: Session, source_id: uuid.UUID, kind: str) -> SourceCoverAsset | None:
    return session.scalar(
        select(SourceCoverAsset).where(
            SourceCoverAsset.source_item_id == source_id,
            SourceCoverAsset.kind == kind,
            SourceCoverAsset.is_current.is_(True),
        )
    )


def resolve_cover(session: Session, source_id: uuid.UUID, document: ExtractedDocument | None) -> ResolvedCover | None:
    from app.services.cover.verification import verify_asset_file

    user = _current_asset(session, source_id, "USER")
    if user is not None:
        ok, _ = verify_asset_file(user.relative_path)
        if ok:
            return ResolvedCover(kind="user", relative_path=user.relative_path)
    metadata_only = bool(
        document is not None
        and isinstance(document.metadata_json, dict)
        and document.metadata_json.get("content_completeness") == "metadata_only"
    )
    if metadata_only:
        # Retain any historical generated asset and run, but do not present an
        # illustration created from a URL/metadata as if it depicted article text.
        remote = preview_image_from_document(document)
        return ResolvedCover(kind="source", remote_url=remote) if remote else None
    generated = _current_asset(session, source_id, "GENERATED")
    if generated is not None:
        ok, _ = verify_asset_file(generated.relative_path)
        if ok:
            return ResolvedCover(kind="generated", relative_path=generated.relative_path)
    remote = preview_image_from_document(document)
    if remote:
        return ResolvedCover(kind="source", remote_url=remote)
    if generated is not None:
        return ResolvedCover(kind="generated", relative_path=generated.relative_path)
    return None


def library_has_cover(session: Session, source_id: uuid.UUID, document: ExtractedDocument | None) -> bool:
    return resolve_cover(session, source_id, document) is not None
