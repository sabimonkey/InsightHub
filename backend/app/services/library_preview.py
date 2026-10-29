"""Safe preview image URL for library cards."""

from __future__ import annotations

import html
import uuid
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.models.extraction import ExtractedDocument
from app.models.source_item import SourceItem
from app.services.extraction.preview_image import resolve_preview_url


def _safe_https_url(value: str | None) -> str | None:
    if not value or not isinstance(value, str):
        return None
    stripped = html.unescape(value.strip())
    if not stripped.lower().startswith(("https://", "http://")):
        return None
    try:
        resolved = resolve_preview_url(stripped, None)
    except Exception:
        return None
    return resolved


def preview_image_from_document(document: ExtractedDocument | None) -> str | None:
    blob = document.metadata_json if document else None
    if not isinstance(blob, dict):
        return None
    for key in (
        "preview_image_url",
        "og_image",
        "og:image",
        "twitter_image",
        "twitter:image",
        "twitter:image:src",
        "thumbnail_url",
    ):
        url = _safe_https_url(blob.get(key))
        if url:
            return url
    return None


def library_preview_proxy_path(session: Session, source_id: uuid.UUID, document: ExtractedDocument | None) -> str | None:
    from sqlalchemy import select

    from app.models.cover import SourceCoverAsset
    from app.services.cover.resolution import resolve_cover

    resolved = resolve_cover(session, source_id, document)
    if resolved is None:
        return None
    version = None
    if resolved.relative_path:
        asset = session.scalar(
            select(SourceCoverAsset).where(
                SourceCoverAsset.source_item_id == source_id,
                SourceCoverAsset.relative_path == resolved.relative_path,
                SourceCoverAsset.is_current.is_(True),
            )
        )
        if asset is not None:
            version = str(asset.id)
    base = f"/api/sources/{source_id}/cover-image"
    return f"{base}?v={version}" if version else base


def library_preview_url(session: Session, source: SourceItem, document: ExtractedDocument | None) -> str | None:
    """Public API field: proxied cover path when a cover asset or source preview exists."""
    return library_preview_proxy_path(session, source.id, document)


def library_cover_origin(session: Session, source_id: uuid.UUID, document: ExtractedDocument | None) -> str | None:
    from app.services.cover.resolution import resolve_cover

    resolved = resolve_cover(session, source_id, document)
    if resolved:
        return resolved.kind
    if (
        document is not None
        and isinstance(document.metadata_json, dict)
        and document.metadata_json.get("content_completeness") == "metadata_only"
    ):
        return "content_incomplete"
    return None


def library_cover_status(source: SourceItem, document: ExtractedDocument | None, session: Session | None = None) -> str:
    if session is not None:
        from app.services.cover.resolution import resolve_cover

        resolved = resolve_cover(session, source.id, document)
        if resolved is not None:
            if resolved.kind == "generated":
                return "GENERATED_COVER"
            if resolved.kind == "user":
                return "USER_COVER"
            return "HAS_PREVIEW"
    blob = document.metadata_json if document and isinstance(document.metadata_json, dict) else {}
    if blob.get("content_completeness") == "metadata_only":
        return "CONTENT_INCOMPLETE"
    if document is None:
        return "NO_EXTRACTION"
    if preview_image_from_document(document):
        return "HAS_PREVIEW"
    blob = document.metadata_json if isinstance(document.metadata_json, dict) else {}
    if blob.get("preview_image_missing"):
        return "NO_IMAGE_IN_SOURCE"
    if source.source_type in {"TEXT", "FILE"}:
        return "NO_IMAGE_IN_SOURCE"
    return "IMAGE_NOT_EXTRACTED"
