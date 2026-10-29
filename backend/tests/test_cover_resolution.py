import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.models.cover import SourceCoverAsset
from app.services.cover.resolution import resolve_cover


def test_generated_cover_when_no_source_image():
    source_id = uuid.uuid4()
    doc = MagicMock()
    doc.metadata_json = {}
    asset = SourceCoverAsset(
        id=uuid.uuid4(),
        source_item_id=source_id,
        kind="GENERATED",
        content_hash="def",
        relative_path="data/covers/x/y.png",
        is_current=True,
        created_at=datetime.now(timezone.utc),
    )
    session = MagicMock()
    session.scalar = MagicMock(side_effect=[None, asset])

    with patch("app.services.cover.verification.verify_asset_file", return_value=(True, None)):
        resolved = resolve_cover(session, source_id, doc)
    assert resolved is not None
    assert resolved.kind == "generated"


def test_readable_generated_beats_source_og():
    source_id = uuid.uuid4()
    doc = MagicMock()
    doc.metadata_json = {"preview_image_url": "https://example.com/og.jpg"}
    asset = SourceCoverAsset(
        id=uuid.uuid4(),
        source_item_id=source_id,
        kind="GENERATED",
        content_hash="def",
        relative_path="data/covers/x/y.png",
        is_current=True,
        created_at=datetime.now(timezone.utc),
    )
    session = MagicMock()
    session.scalar = MagicMock(side_effect=[None, asset])

    with patch("app.services.cover.verification.verify_asset_file", return_value=(True, None)):
        resolved = resolve_cover(session, source_id, doc)
    assert resolved.kind == "generated"


def test_source_og_when_no_generated_asset():
    source_id = uuid.uuid4()
    doc = MagicMock()
    doc.metadata_json = {"preview_image_url": "https://example.com/og.jpg"}
    session = MagicMock()
    session.scalar = MagicMock(side_effect=[None, None])
    with patch("app.services.cover.verification.verify_asset_file", return_value=(True, None)):
        resolved = resolve_cover(session, source_id, doc)
    assert resolved.kind == "source"
    assert resolved.remote_url == "https://example.com/og.jpg"


def test_metadata_only_document_hides_historical_generated_asset():
    source_id = uuid.uuid4()
    doc = MagicMock()
    doc.metadata_json = {"content_completeness": "metadata_only"}
    session = MagicMock()
    session.scalar = MagicMock(return_value=None)

    resolved = resolve_cover(session, source_id, doc)

    assert resolved is None
    # Only the user-supplied asset lookup runs. The historical generated asset
    # remains stored but is not eligible for current library display.
    assert session.scalar.call_count == 1
