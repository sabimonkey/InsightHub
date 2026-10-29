import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.models.enums import DuplicateReason, IngestionOrigin, IngestionStatus, IngestionType, SourceType
from app.models.ingestion_record import IngestionRecord
from app.models.source_asset import SourceAsset
from app.models.source_item import SourceItem
from app.services.ingestion.errors import IngestionError
from app.services.ingestion.file_policy import classify_source_type, guess_mime_type, validate_filename
from app.services.ingestion.storage import (
    file_sha256,
    new_temp_path,
    place_content_addressed,
    relative_raw_path,
    stream_to_temp,
)
from app.services.ingestion.text_hash import ensure_text_acceptable, text_content_hash, text_display_name
from app.services.ingestion.url_normalization import canonicalize_url
from app.core.config import get_settings
from app.services.system_scope import USER_SCOPE, api_visibility_filter, creation_scope_from_settings


@dataclass
class IngestResult:
    source_item: SourceItem
    ingestion_record: IngestionRecord
    asset: SourceAsset | None
    duplicate_detected: bool
    duplicate_reason: str | None


class IngestionService:
    def __init__(self, session: Session, raw_root: Path, max_upload_size_bytes: int) -> None:
        self.session = session
        self.raw_root = raw_root
        self.max_upload_size_bytes = max_upload_size_bytes

    def _creation_scope(self) -> str:
        return creation_scope_from_settings(get_settings())

    def _require_same_scope(self, source: SourceItem) -> None:
        if source.system_scope != self._creation_scope():
            raise IngestionError(409, "SOURCE_SCOPE_CONFLICT", "相同内容已存在于另一个数据作用域，未复用或修改该资料。")

    def ingest_url(self, raw_url: str) -> IngestResult:
        original, canonical = canonicalize_url(raw_url)
        existing = self.session.scalar(select(SourceItem).where(SourceItem.canonical_url == canonical))
        if existing is not None:
            self._require_same_scope(existing)
            record = self._add_ingestion(
                source=existing,
                ingestion_type=IngestionType.URL,
                original_input=original,
                duplicate=True,
                reason=DuplicateReason.CANONICAL_URL_DUPLICATE,
            )
            self._commit()
            return IngestResult(existing, record, None, True, DuplicateReason.CANONICAL_URL_DUPLICATE.value)
        source = SourceItem(
            id=uuid.uuid4(),
            source_type=SourceType.URL.value,
            original_url=original,
            canonical_url=canonical,
            display_name=canonical,
            content_hash=None,
            status=IngestionStatus.STORED.value,
            system_scope=self._creation_scope(),
        )
        self.session.add(source)
        record = self._add_ingestion(
            source=source,
            ingestion_type=IngestionType.URL,
            original_input=original,
            duplicate=False,
            reason=None,
        )
        try:
            self._commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.session.scalar(select(SourceItem).where(SourceItem.canonical_url == canonical))
            if existing is None:
                raise
            self._require_same_scope(existing)
            record = self._add_ingestion(
                source=existing,
                ingestion_type=IngestionType.URL,
                original_input=original,
                duplicate=True,
                reason=DuplicateReason.CANONICAL_URL_DUPLICATE,
            )
            self._commit()
            return IngestResult(existing, record, None, True, DuplicateReason.CANONICAL_URL_DUPLICATE.value)
        return IngestResult(source, record, None, False, None)

    def ingest_discovered_url(self, raw_url: str) -> IngestResult:
        original, canonical = canonicalize_url(raw_url)
        existing = self.session.scalar(select(SourceItem).where(SourceItem.canonical_url == canonical))
        if existing is not None:
            self._require_same_scope(existing)
            record = self._add_ingestion(
                source=existing,
                ingestion_type=IngestionType.URL,
                original_input=original,
                duplicate=True,
                reason=DuplicateReason.CANONICAL_URL_DUPLICATE,
                origin=IngestionOrigin.SYSTEM_DISCOVERY,
            )
            self._commit()
            return IngestResult(existing, record, None, True, DuplicateReason.CANONICAL_URL_DUPLICATE.value)
        source = SourceItem(
            id=uuid.uuid4(),
            source_type=SourceType.URL.value,
            original_url=original,
            canonical_url=canonical,
            display_name=canonical,
            content_hash=None,
            status=IngestionStatus.STORED.value,
            system_scope=self._creation_scope(),
        )
        self.session.add(source)
        record = self._add_ingestion(
            source=source,
            ingestion_type=IngestionType.URL,
            original_input=original,
            duplicate=False,
            reason=None,
            origin=IngestionOrigin.SYSTEM_DISCOVERY,
        )
        try:
            self._commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.session.scalar(select(SourceItem).where(SourceItem.canonical_url == canonical))
            if existing is None:
                raise
            self._require_same_scope(existing)
            record = self._add_ingestion(
                source=existing,
                ingestion_type=IngestionType.URL,
                original_input=original,
                duplicate=True,
                reason=DuplicateReason.CANONICAL_URL_DUPLICATE,
                origin=IngestionOrigin.SYSTEM_DISCOVERY,
            )
            self._commit()
            return IngestResult(existing, record, None, True, DuplicateReason.CANONICAL_URL_DUPLICATE.value)
        return IngestResult(source, record, None, False, None)

    def ingest_text(self, text: str) -> IngestResult:
        ensure_text_acceptable(text, self.max_upload_size_bytes)
        digest = text_content_hash(text)
        existing = self.session.scalar(
            select(SourceItem).where(
                SourceItem.source_type == SourceType.TEXT.value,
                SourceItem.content_hash == digest,
            )
        )
        if existing is not None:
            self._require_same_scope(existing)
            record = self._add_ingestion(
                source=existing,
                ingestion_type=IngestionType.TEXT,
                original_input=text,
                duplicate=True,
                reason=DuplicateReason.EXACT_TEXT_DUPLICATE,
            )
            self._commit()
            return IngestResult(existing, record, None, True, DuplicateReason.EXACT_TEXT_DUPLICATE.value)
        source = SourceItem(
            id=uuid.uuid4(),
            source_type=SourceType.TEXT.value,
            original_url=None,
            canonical_url=None,
            display_name=text_display_name(text),
            content_hash=digest,
            status=IngestionStatus.STORED.value,
            system_scope=self._creation_scope(),
        )
        self.session.add(source)
        record = self._add_ingestion(
            source=source,
            ingestion_type=IngestionType.TEXT,
            original_input=text,
            duplicate=False,
            reason=None,
        )
        try:
            self._commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.session.scalar(
                select(SourceItem).where(
                    SourceItem.source_type == SourceType.TEXT.value,
                    SourceItem.content_hash == digest,
                )
            )
            if existing is None:
                raise
            self._require_same_scope(existing)
            record = self._add_ingestion(
                source=existing,
                ingestion_type=IngestionType.TEXT,
                original_input=text,
                duplicate=True,
                reason=DuplicateReason.EXACT_TEXT_DUPLICATE,
            )
            self._commit()
            return IngestResult(existing, record, None, True, DuplicateReason.EXACT_TEXT_DUPLICATE.value)
        return IngestResult(source, record, None, False, None)

    def ingest_file(self, filename: str | None, fileobj: BinaryIO, content_type: str | None) -> IngestResult:
        safe_name = validate_filename(filename)
        temp_path = new_temp_path(self.raw_root)
        digest, size = stream_to_temp(fileobj, temp_path, self.max_upload_size_bytes)
        return self._finalize_file(safe_name, content_type, digest, size, temp_path)

    def _finalize_file(
        self,
        filename: str,
        content_type: str | None,
        digest: str,
        size: int,
        temp_path: Path,
    ) -> IngestResult:
        created_path: Path | None = None
        try:
            existing = self.session.scalar(select(SourceAsset).where(SourceAsset.sha256 == digest))
            if existing is not None:
                existing_source = self.session.get(SourceItem, existing.source_item_id)
                if existing_source is None:
                    raise IngestionError(500, "STORAGE_FAILED", "已有文件记录缺少 Source。")
                self._require_same_scope(existing_source)
                temp_path.unlink(missing_ok=True)
                record = self._add_ingestion(
                    source=existing_source,
                    ingestion_type=IngestionType.FILE,
                    original_input=filename,
                    duplicate=True,
                    reason=DuplicateReason.EXACT_FILE_DUPLICATE,
                )
                self._commit()
                return IngestResult(existing_source, record, existing, True, DuplicateReason.EXACT_FILE_DUPLICATE.value)

            relative = relative_raw_path(digest)
            destination = self.raw_root / relative
            if destination.exists():
                if file_sha256(destination) != digest:
                    temp_path.unlink(missing_ok=True)
                    raise IngestionError(500, "STORAGE_CONFLICT", "原始文件路径已被不同内容占用，未覆盖。")
                temp_path.unlink(missing_ok=True)
            else:
                created = place_content_addressed(temp_path, destination)
                if created:
                    created_path = destination
                elif file_sha256(destination) != digest:
                    raise IngestionError(500, "STORAGE_CONFLICT", "原始文件路径已被不同内容占用，未覆盖。")

            mime_type = guess_mime_type(filename, content_type)
            source = SourceItem(
                id=uuid.uuid4(),
                source_type=classify_source_type(filename).value,
                original_url=None,
                canonical_url=None,
                display_name=filename,
                content_hash=digest,
                status=IngestionStatus.STORED.value,
                system_scope=self._creation_scope(),
            )
            self.session.add(source)
            self.session.flush()
            asset = SourceAsset(
                source_item_id=source.id,
                original_filename=filename,
                stored_path=relative.replace("\\", "/"),
                mime_type=mime_type,
                size_bytes=size,
                sha256=digest,
            )
            self.session.add(asset)
            record = self._add_ingestion(
                source=source,
                ingestion_type=IngestionType.FILE,
                original_input=filename,
                duplicate=False,
                reason=None,
            )
            self._commit()
            created_path = None
            return IngestResult(source, record, asset, False, None)
        except IntegrityError:
            self.session.rollback()
            existing = self.session.scalar(select(SourceAsset).where(SourceAsset.sha256 == digest))
            if existing is None:
                self._delete_if_unreferenced(created_path, digest)
                raise
            source = self.session.get(SourceItem, existing.source_item_id)
            if source is None:
                raise IngestionError(500, "STORAGE_FAILED", "已有文件记录缺少 Source。")
            self._require_same_scope(source)
            record = self._add_ingestion(
                source=source,
                ingestion_type=IngestionType.FILE,
                original_input=filename,
                duplicate=True,
                reason=DuplicateReason.EXACT_FILE_DUPLICATE,
            )
            self._commit()
            return IngestResult(source, record, existing, True, DuplicateReason.EXACT_FILE_DUPLICATE.value)
        except Exception:
            self.session.rollback()
            temp_path.unlink(missing_ok=True)
            self._delete_if_unreferenced(created_path, digest)
            raise

    def list_inbox(self, page: int, page_size: int, status_filter: str) -> tuple[list[tuple[IngestionRecord, SourceItem | None, SourceAsset | None]], int]:
        if page < 1 or page_size < 1 or page_size > 100:
            raise IngestionError(400, "INVALID_PAGE", "分页参数无效。")
        if status_filter not in {"all", "success", "failed", "duplicate"}:
            raise IngestionError(400, "INVALID_FILTER", "筛选条件无效。")
        from sqlalchemy import or_

        stmt = (
            select(IngestionRecord, SourceItem, SourceAsset)
            .join(SourceItem, IngestionRecord.source_item_id == SourceItem.id, isouter=True)
            .join(SourceAsset, SourceAsset.source_item_id == SourceItem.id, isouter=True)
            .where(or_(SourceItem.id.is_(None), api_visibility_filter(SourceItem.system_scope)))
        )
        if status_filter == "success":
            stmt = stmt.where(
                IngestionRecord.status == IngestionStatus.STORED.value,
                IngestionRecord.duplicate_detected.is_(False),
            )
        elif status_filter == "failed":
            stmt = stmt.where(IngestionRecord.status == IngestionStatus.FAILED.value)
        elif status_filter == "duplicate":
            stmt = stmt.where(IngestionRecord.duplicate_detected.is_(True))
        total = self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.session.execute(
            stmt.order_by(IngestionRecord.collected_at.desc(), IngestionRecord.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [(row[0], row[1], row[2]) for row in rows], int(total)

    def get_source(self, source_id: uuid.UUID) -> tuple[SourceItem, SourceAsset | None, list[IngestionRecord]]:
        source = self.session.get(SourceItem, source_id)
        if source is None:
            raise IngestionError(404, "SOURCE_NOT_FOUND", "找不到该资料。")
        asset = self.session.scalar(select(SourceAsset).where(SourceAsset.source_item_id == source.id))
        records = list(
            self.session.scalars(
                select(IngestionRecord)
                .where(IngestionRecord.source_item_id == source.id)
                .order_by(IngestionRecord.collected_at.asc())
            ).all()
        )
        return source, asset, records

    def _add_ingestion(
        self,
        source: SourceItem,
        ingestion_type: IngestionType,
        original_input: str,
        duplicate: bool,
        reason: DuplicateReason | None,
        origin: IngestionOrigin = IngestionOrigin.USER_COLLECTION,
    ) -> IngestionRecord:
        record = IngestionRecord(
            source_item_id=source.id,
            ingestion_type=ingestion_type.value,
            origin=origin.value,
            original_input=original_input,
            collected_at=datetime.now(timezone.utc),
            duplicate_detected=duplicate,
            duplicate_reason=reason.value if reason else None,
            status=IngestionStatus.STORED.value,
        )
        self.session.add(record)
        return record

    def _commit(self) -> None:
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def _delete_if_unreferenced(self, path: Path | None, digest: str) -> None:
        if path is None or not path.exists():
            return
        existing = self.session.scalar(select(SourceAsset.id).where(SourceAsset.sha256 == digest))
        if existing is None:
            path.unlink(missing_ok=True)
