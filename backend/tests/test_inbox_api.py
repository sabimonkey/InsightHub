from app.models.enums import IngestionStatus, IngestionType
from app.models.ingestion_record import IngestionRecord
from datetime import datetime, timezone


def test_inbox_list_and_source_detail(client, db_session) -> None:
    created = client.post("/api/ingest/text", json={"text": "inbox row"})
    assert created.status_code == 200
    source_id = created.json()["source"]["id"]
    client.post("/api/ingest/text", json={"text": "inbox row"})

    listed = client.get("/api/inbox", params={"filter": "all", "page": 1, "page_size": 100})
    assert listed.status_code == 200
    page = listed.json()
    own = [item for item in page["items"] if item["source_id"] == source_id]
    assert len(own) == 2
    assert {item["duplicate_detected"] for item in own} == {False, True}

    duplicates = client.get("/api/inbox", params={"filter": "duplicate", "page_size": 100})
    assert duplicates.status_code == 200
    duplicate_own = [item for item in duplicates.json()["items"] if item["source_id"] == source_id]
    assert len(duplicate_own) == 1
    assert duplicate_own[0]["duplicate_detected"] is True

    success = client.get("/api/inbox", params={"filter": "success", "page_size": 100})
    success_own = [item for item in success.json()["items"] if item["source_id"] == source_id]
    assert len(success_own) == 1
    assert success_own[0]["duplicate_detected"] is False

    detail = client.get(f"/api/sources/{source_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["source"]["id"] == source_id
    assert body["source"]["content_hash"]
    assert len(body["ingestions"]) == 2
    assert body["asset"] is None

    missing = client.get("/api/sources/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404

    failed = IngestionRecord(
        ingestion_type=IngestionType.TEXT.value,
        original_input="failed input",
        collected_at=datetime.now(timezone.utc),
        duplicate_detected=False,
        duplicate_reason=None,
        status=IngestionStatus.FAILED.value,
        source_item_id=None,
    )
    db_session.add(failed)
    db_session.commit()
    failed_page = client.get("/api/inbox", params={"filter": "failed", "page_size": 100})
    assert failed_page.status_code == 200
    failed_own = [item for item in failed_page.json()["items"] if item["display_name"] == "failed input"]
    assert len(failed_own) == 1
    assert failed_own[0]["status"] == "FAILED"
