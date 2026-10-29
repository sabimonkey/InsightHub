from sqlalchemy import func, select

from app.models.ingestion_record import IngestionRecord
from app.models.source_item import SourceItem


def test_url_ingestion_and_duplicate(client) -> None:
    first = client.post(
        "/api/ingest/url",
        json={"url": "https://x.com/example/status/123?s=46&utm_source=test"},
    )
    assert first.status_code == 200
    body = first.json()
    assert body["duplicate_detected"] is False
    assert body["source"]["canonical_url"] == "https://x.com/example/status/123"
    assert body["source"]["original_url"] == "https://x.com/example/status/123?s=46&utm_source=test"

    second = client.post("/api/ingest/url", json={"url": "https://x.com/example/status/123"})
    assert second.status_code == 200
    again = second.json()
    assert again["duplicate_detected"] is True
    assert again["duplicate_reason"] == "CANONICAL_URL_DUPLICATE"
    assert "已识别重复资料" in again["message"]
    assert "已复用已有 Source" in again["message"]
    assert "本次收集记录已保存" in again["message"]
    assert again["source"]["id"] == body["source"]["id"]
    assert again["ingestion"]["id"] != body["ingestion"]["id"]


def test_invalid_url_is_rejected(client) -> None:
    response = client.post("/api/ingest/url", json={"url": "not-a-url"})
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_URL"


def test_url_rows(client, db_session) -> None:
    client.post("/api/ingest/url", json={"url": "https://example.com/post?utm_medium=email"})
    client.post("/api/ingest/url", json={"url": "https://example.com/post"})
    sources = db_session.scalar(
        select(func.count()).select_from(SourceItem).where(SourceItem.canonical_url == "https://example.com/post")
    )
    records = db_session.scalar(
        select(func.count())
        .select_from(IngestionRecord)
        .join(SourceItem, IngestionRecord.source_item_id == SourceItem.id)
        .where(SourceItem.canonical_url == "https://example.com/post")
    )
    assert sources == 1
    assert records == 2
