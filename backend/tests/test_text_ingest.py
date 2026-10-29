from sqlalchemy import func, select

from app.models.ingestion_record import IngestionRecord
from app.models.source_item import SourceItem


def test_text_ingestion_and_exact_duplicate(client, db_session) -> None:
    first = client.post("/api/ingest/text", json={"text": "hello\r\nworld"})
    assert first.status_code == 200
    assert first.json()["duplicate_detected"] is False
    assert first.json()["source"]["source_type"] == "TEXT"

    second = client.post("/api/ingest/text", json={"text": "hello\nworld"})
    assert second.status_code == 200
    body = second.json()
    assert body["duplicate_detected"] is True
    assert body["duplicate_reason"] == "EXACT_TEXT_DUPLICATE"
    assert body["source"]["id"] == first.json()["source"]["id"]

    digest = body["source"]["content_hash"]
    sources = db_session.scalar(
        select(func.count()).select_from(SourceItem).where(SourceItem.content_hash == digest)
    )
    records = db_session.scalar(
        select(func.count()).select_from(IngestionRecord).where(IngestionRecord.source_item_id == body["source"]["id"])
    )
    assert sources == 1
    assert records == 2


def test_empty_text_is_rejected(client) -> None:
    response = client.post("/api/ingest/text", json={"text": "  \n\t "})
    assert response.status_code == 400
    assert response.json()["code"] == "EMPTY_TEXT"
