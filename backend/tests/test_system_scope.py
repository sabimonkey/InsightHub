import uuid

from app.core.config import Settings
from datetime import datetime, timezone

from app.models.enums import IngestionType
from app.models.ingestion_record import IngestionRecord
from app.models.source_item import SourceItem
from app.services.ingestion.service import IngestionService
from app.services.system_scope import AUTOMATION_TEST_SCOPE, USER_SCOPE, api_visibility_filter, creation_scope_from_settings


def test_creation_scope_from_settings():
    user = Settings(insighthub_system_scope="USER")
    auto = Settings(insighthub_system_scope="AUTOMATION_TEST")
    assert creation_scope_from_settings(user) == USER_SCOPE
    assert creation_scope_from_settings(auto) == AUTOMATION_TEST_SCOPE


def test_scope_visible_for_api():
    from app.core.config import Settings
    from app.services.system_scope import AUTOMATION_TEST_SCOPE, USER_SCOPE, scope_visible_for_api

    user_settings = Settings(insighthub_system_scope="USER")
    auto_settings = Settings(insighthub_system_scope=AUTOMATION_TEST_SCOPE)
    assert scope_visible_for_api(USER_SCOPE, user_settings)
    assert not scope_visible_for_api(AUTOMATION_TEST_SCOPE, user_settings)
    assert scope_visible_for_api(AUTOMATION_TEST_SCOPE, auto_settings)
    assert not scope_visible_for_api(USER_SCOPE, auto_settings)


def test_inbox_excludes_automation_scope(db_session, raw_root, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("INSIGHTHUB_SYSTEM_SCOPE", USER_SCOPE)
    get_settings.cache_clear()
    auto = SourceItem(
        id=uuid.uuid4(),
        source_type="TEXT",
        display_name="e2e-hidden",
        status="STORED",
        system_scope=AUTOMATION_TEST_SCOPE,
        content_hash="a" * 64,
    )
    user = SourceItem(
        id=uuid.uuid4(),
        source_type="TEXT",
        display_name="user-visible",
        status="STORED",
        system_scope=USER_SCOPE,
        content_hash="b" * 64,
    )
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            auto,
            user,
            IngestionRecord(
                id=uuid.uuid4(),
                source_item_id=auto.id,
                ingestion_type=IngestionType.TEXT.value,
                original_input="e2e-hidden",
                collected_at=now,
                status="STORED",
            ),
            IngestionRecord(
                id=uuid.uuid4(),
                source_item_id=user.id,
                ingestion_type=IngestionType.TEXT.value,
                original_input="user-visible",
                collected_at=now,
                status="STORED",
            ),
        ]
    )
    db_session.commit()
    service = IngestionService(db_session, raw_root, 1_000_000)
    rows, total = service.list_inbox(1, 50, "all")
    names = {source.display_name for _r, source, _a in rows if source}
    assert "user-visible" in names
    assert "e2e-hidden" not in names
    assert total >= 1
