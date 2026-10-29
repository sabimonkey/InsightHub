import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.models.cover import CoverGenerationRun, SourceCoverAsset
from app.services.cover.verification import effective_run_success, verify_asset_file


def test_verify_asset_file_rejects_tiny_payload():
    with patch("app.services.cover.verification.read_cover_file", return_value=(b"x" * 10, "image/jpeg")):
        ok, code = verify_asset_file("data/covers/x/y.jpg")
    assert ok is False
    assert code == "COVER_OUTPUT_MISSING"


def test_effective_run_success_requires_readable_asset():
    source_id = uuid.uuid4()
    asset_id = uuid.uuid4()
    run = CoverGenerationRun(
        id=uuid.uuid4(),
        source_item_id=source_id,
        status="SUCCEEDED",
        stage="SUCCEEDED",
        asset_id=asset_id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    asset = SourceCoverAsset(
        id=asset_id,
        source_item_id=source_id,
        kind="GENERATED",
        content_hash="abc",
        relative_path="data/covers/a/b.jpg",
        is_current=True,
        created_at=datetime.now(timezone.utc),
    )
    session = MagicMock()
    session.get.return_value = asset
    with patch("app.services.cover.verification.verify_asset_file", return_value=(True, None)):
        ok, err = effective_run_success(session, run)
    assert ok is True
    assert err is None


def test_effective_run_success_fails_when_run_succeeded_but_file_bad():
    source_id = uuid.uuid4()
    asset_id = uuid.uuid4()
    run = CoverGenerationRun(
        id=uuid.uuid4(),
        source_item_id=source_id,
        status="SUCCEEDED",
        stage="SUCCEEDED",
        asset_id=asset_id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    asset = SourceCoverAsset(
        id=asset_id,
        source_item_id=source_id,
        kind="GENERATED",
        content_hash="abc",
        relative_path="data/covers/a/b.jpg",
        is_current=True,
        created_at=datetime.now(timezone.utc),
    )
    session = MagicMock()
    session.get.return_value = asset
    with patch("app.services.cover.verification.verify_asset_file", return_value=(False, "COVER_STORAGE_FAILED")):
        ok, err = effective_run_success(session, run)
    assert ok is False
    assert err == "COVER_STORAGE_FAILED"
