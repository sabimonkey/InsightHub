from datetime import datetime, timezone

from app.core.config import get_settings
from app.models.source_item import SourceItem
from app.services.cover.auto import audit_cover_funnel, classify_source_cover_bucket, maybe_enqueue_auto_cover


def test_audit_funnel_empty_user_scope(db_session):
    report = audit_cover_funnel(db_session)
    assert "buckets" in report
    assert report["total_sources"] >= 0


def test_auto_enqueue_respects_disabled(db_session, monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "fake")
    settings = get_settings().model_copy(update={"cover_auto_enabled": False, "minimax_enable_fake": True})
    now = datetime.now(timezone.utc)
    source = SourceItem(
        id=__import__("uuid").uuid4(),
        source_type="URL",
        display_name="Auto cover disabled path",
        status="STORED",
        privacy_level="PRIVATE",
        system_scope="AUTOMATION_TEST",
        created_at=now,
        updated_at=now,
    )
    db_session.add(source)
    db_session.commit()
    assert maybe_enqueue_auto_cover(db_session, source.id, settings=settings) is None
    bucket = classify_source_cover_bucket(db_session, source, settings=settings)
    assert bucket in {"not_eligible_extraction", "not_eligible_analysis", "eligible_missing_cover"}
