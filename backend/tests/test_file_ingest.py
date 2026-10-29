import hashlib
import io

import pytest
from sqlalchemy import func, select

from app.models.ingestion_record import IngestionRecord
from app.models.source_asset import SourceAsset
from app.models.source_item import SourceItem
from app.services.ingestion.errors import IngestionError
from app.services.ingestion.service import IngestionService


HELLO_SHA = hashlib.sha256(b"hello-pdf").hexdigest()


def test_file_upload_hash_and_duplicate(client, db_session, raw_root) -> None:
    first = client.post(
        "/api/ingest/file",
        files={"file": ("example.pdf", b"hello-pdf", "application/pdf")},
    )
    assert first.status_code == 200
    body = first.json()
    assert body["duplicate_detected"] is False
    assert body["source"]["source_type"] == "PDF"
    assert body["asset"]["sha256"] == HELLO_SHA
    assert body["asset"]["original_filename"] == "example.pdf"
    assert body["asset"]["size_bytes"] == len(b"hello-pdf")
    stored = raw_root / body["asset"]["stored_path"]
    assert stored.is_file()
    assert stored.read_bytes() == b"hello-pdf"
    assert "example.pdf" not in body["asset"]["stored_path"]

    second = client.post(
        "/api/ingest/file",
        files={"file": ("copy.pdf", b"hello-pdf", "application/pdf")},
    )
    assert second.status_code == 200
    again = second.json()
    assert again["duplicate_detected"] is True
    assert again["duplicate_reason"] == "EXACT_FILE_DUPLICATE"
    assert again["source"]["id"] == body["source"]["id"]
    assert list(raw_root.rglob("*.bin")) == [stored]

    assets = db_session.scalar(select(func.count()).select_from(SourceAsset).where(SourceAsset.sha256 == HELLO_SHA))
    records = db_session.scalar(
        select(func.count()).select_from(IngestionRecord).where(IngestionRecord.source_item_id == body["source"]["id"])
    )
    assert assets == 1
    assert records == 2


def test_same_filename_different_bytes_are_distinct(client) -> None:
    first = client.post("/api/ingest/file", files={"file": ("report.pdf", b"alpha", "application/pdf")})
    second = client.post("/api/ingest/file", files={"file": ("report.pdf", b"beta", "application/pdf")})
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["duplicate_detected"] is False
    assert second.json()["duplicate_detected"] is False
    assert first.json()["source"]["id"] != second.json()["source"]["id"]


def test_dangerous_filename_and_forbidden_extension(client, db_session) -> None:
    before = db_session.scalar(select(func.count()).select_from(SourceItem))
    traversal = client.post("/api/ingest/file", files={"file": ("../secret.pdf", b"x", "application/pdf")})
    assert traversal.status_code == 400
    assert traversal.json()["code"] == "UNSAFE_FILENAME"
    forbidden = client.post("/api/ingest/file", files={"file": ("run.exe", b"x", "application/octet-stream")})
    assert forbidden.status_code == 400
    assert forbidden.json()["code"] == "FORBIDDEN_EXTENSION"
    assert db_session.scalar(select(func.count()).select_from(SourceItem)) == before


def test_oversize_upload(client) -> None:
    response = client.post("/api/ingest/file", files={"file": ("big.pdf", b"x" * 1025, "application/pdf")})
    assert response.status_code == 413
    assert response.json()["code"] == "FILE_TOO_LARGE"


def test_batch_partial_failure(client) -> None:
    response = client.post(
        "/api/ingest/files",
        files=[
            ("files", ("ok.md", b"notes", "text/markdown")),
            ("files", ("bad.ps1", b"nope", "text/plain")),
        ],
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert results[0]["ok"] is True
    assert results[0]["source_id"]
    assert results[1]["ok"] is False
    assert results[1]["code"] == "FORBIDDEN_EXTENSION"


def test_db_failure_removes_new_file(db_session, raw_root, monkeypatch) -> None:
    before = db_session.scalar(select(func.count()).select_from(SourceItem))
    service = IngestionService(db_session, raw_root, max_upload_size_bytes=10_000)

    def fail_commit() -> None:
        raise RuntimeError("db failed")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="db failed"):
        service.ingest_file("notes.md", io.BytesIO(b"markdown"), "text/markdown")
    assert list(raw_root.rglob("*.bin")) == []
    assert db_session.scalar(select(func.count()).select_from(SourceItem)) == before


def test_save_failure_writes_no_row(db_session, raw_root, monkeypatch) -> None:
    before = db_session.scalar(select(func.count()).select_from(SourceItem))
    service = IngestionService(db_session, raw_root, max_upload_size_bytes=10_000)

    def fail_stream(*_args, **_kwargs):
        raise IngestionError(500, "STORAGE_FAILED", "文件保存失败，未写入数据库。")

    monkeypatch.setattr("app.services.ingestion.service.stream_to_temp", fail_stream)
    with pytest.raises(IngestionError):
        service.ingest_file("notes.md", io.BytesIO(b"markdown"), "text/markdown")
    assert db_session.scalar(select(func.count()).select_from(SourceItem)) == before
    assert list(raw_root.rglob("*.bin")) == []
