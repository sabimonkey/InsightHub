import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.enums import IngestionStatus, IngestionType, SourceType
from app.models.extraction import ContentChunk, ExtractedDocument, ExtractionRun
from app.models.ingestion_record import IngestionRecord
from app.models.source_asset import SourceAsset
from app.models.source_item import SourceItem
from app.services.extraction.chunking import chunk_blocks
from app.services.extraction.docx_extractor import extract_docx
from app.services.extraction.enums import ExtractionStatus, ExtractionTrigger
from app.services.extraction.image_extractor import extract_image, recognize_image_bytes
from app.services.extraction.markdown_extractor import extract_markdown
from app.services.extraction.pdf_extractor import extract_pdf
from app.services.extraction.text_extractor import extract_text
from app.services.extraction.types import ExtractionPayload
from app.services.extraction.browser_renderer import BrowserRenderer
from app.services.extraction.browser_renderer import PlaywrightBrowserRenderer
from app.services.extraction.web_fallback import extract_web_with_fallback
from app.services.extraction.types import ExtractedBlock
from app.services.extraction.enums import ChunkType
from app.services.ingestion.text_hash import ensure_text_acceptable

SYNC_SOURCE_TYPES = {SourceType.TEXT.value, SourceType.MARKDOWN.value}
ACTIVE_STATUSES = {
    ExtractionStatus.PENDING.value,
    ExtractionStatus.RUNNING.value,
    ExtractionStatus.SUCCEEDED.value,
    ExtractionStatus.PARTIAL.value,
}


class ExtractionService:
    def __init__(
        self,
        session: Session,
        raw_root: Path,
        extracted_root: Path,
        *,
        inline: bool,
        chunk_max_chars: int,
        chunk_overlap_chars: int,
        max_pdf_pages: int,
        web_timeout: float,
        web_max_bytes: int,
        web_max_redirects: int,
        web_browser_fallback_enabled: bool = True,
        web_browser_timeout_seconds: float = 25,
        web_browser_settle_ms: int = 800,
        enqueue=None,
        ocr_image=None,
        http_client=None,
        resolver=None,
        browser_renderer: BrowserRenderer | None = None,
        zai_file_parser=None,
        zai_file_parser_enabled: bool = False,
    ) -> None:
        self.session = session
        self.raw_root = raw_root
        self.extracted_root = extracted_root
        self.inline = inline
        self.chunk_max_chars = chunk_max_chars
        self.chunk_overlap_chars = chunk_overlap_chars
        self.max_pdf_pages = max_pdf_pages
        self.web_timeout = web_timeout
        self.web_max_bytes = web_max_bytes
        self.web_max_redirects = web_max_redirects
        self.web_browser_fallback_enabled = web_browser_fallback_enabled
        self.web_browser_timeout_seconds = web_browser_timeout_seconds
        self.web_browser_settle_ms = web_browser_settle_ms
        self.enqueue = enqueue
        self.ocr_image = ocr_image or recognize_image_bytes
        self.http_client = http_client
        self.resolver = resolver
        self._browser_renderer = browser_renderer
        self.zai_file_parser = zai_file_parser
        self.zai_file_parser_enabled = zai_file_parser_enabled

    def schedule(self, source_id: uuid.UUID, trigger: str, force: bool = False) -> ExtractionRun:
        source = self.session.get(SourceItem, source_id)
        if source is None:
            raise LookupError("SOURCE_NOT_FOUND")
        inflight = self.session.scalar(
            select(ExtractionRun).where(
                ExtractionRun.source_item_id == source_id,
                ExtractionRun.status.in_([ExtractionStatus.PENDING.value, ExtractionStatus.RUNNING.value]),
            )
        )
        if inflight is not None:
            if force:
                raise RuntimeError("EXTRACTION_IN_PROGRESS")
            return inflight
        if not force:
            current = self._current_run(source_id)
            if current is not None and current.status in {
                ExtractionStatus.SUCCEEDED.value,
                ExtractionStatus.PARTIAL.value,
            }:
                return current
        asset = self.session.scalar(select(SourceAsset).where(SourceAsset.source_item_id == source_id))
        run = ExtractionRun(
            id=uuid.uuid4(),
            source_item_id=source_id,
            source_asset_id=asset.id if asset else None,
            status=ExtractionStatus.PENDING.value,
            trigger=trigger,
            is_current=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.session.add(run)
        self.session.commit()
        if source.source_type in SYNC_SOURCE_TYPES or self.inline:
            self.execute(run.id)
        elif self.enqueue is not None:
            self.enqueue(str(run.id))
        else:
            self._fail(run, "QUEUE_UNAVAILABLE", "提取任务没有进入队列。")
        self.session.refresh(run)
        return run

    def execute(self, run_id: uuid.UUID) -> ExtractionRun:
        run = self.session.get(ExtractionRun, run_id)
        if run is None:
            raise LookupError("RUN_NOT_FOUND")
        run.status = ExtractionStatus.RUNNING.value
        run.updated_at = datetime.now(timezone.utc)
        self.session.commit()
        try:
            source = self.session.get(SourceItem, run.source_item_id)
            if source is None:
                raise LookupError("SOURCE_NOT_FOUND")
            asset = self.session.get(SourceAsset, run.source_asset_id) if run.source_asset_id else None
            payload = self._extract(source, asset, run.id)
            self._persist(run, source, asset, payload)
        except Exception as exc:
            self.session.rollback()
            run = self.session.get(ExtractionRun, run_id)
            if run is not None:
                self._fail(run, "EXTRACTION_FAILED", _safe_error(exc))
        if run is None:
            raise LookupError("RUN_NOT_FOUND")
        self.session.refresh(run)
        return run

    def current_view(self, source_id: uuid.UUID) -> tuple[ExtractionRun | None, ExtractedDocument | None, list[ContentChunk]]:
        run = self.session.scalar(
            select(ExtractionRun)
            .where(ExtractionRun.source_item_id == source_id)
            .order_by(ExtractionRun.created_at.desc(), ExtractionRun.id.desc())
        )
        if run is None:
            return None, None, []
        document = self.session.scalar(select(ExtractedDocument).where(ExtractedDocument.extraction_run_id == run.id))
        chunks: list[ContentChunk] = []
        if document is not None:
            chunks = list(
                self.session.scalars(
                    select(ContentChunk)
                    .where(ContentChunk.extracted_document_id == document.id)
                    .order_by(ContentChunk.sequence.asc())
                ).all()
            )
        return run, document, chunks

    def _current_run(self, source_id: uuid.UUID) -> ExtractionRun | None:
        return self.session.scalar(
            select(ExtractionRun).where(
                ExtractionRun.source_item_id == source_id,
                ExtractionRun.is_current.is_(True),
            )
        )

    def _extract(self, source: SourceItem, asset: SourceAsset | None, run_id: uuid.UUID) -> ExtractionPayload:
        if source.source_type == SourceType.TEXT.value:
            return extract_text(self._original_text(source.id))
        if source.source_type == SourceType.MARKDOWN.value:
            return extract_markdown(self._file_text(asset) if asset else self._original_text(source.id))
        if source.source_type == SourceType.DOCX.value:
            cloud = self._zai_file_payload(source, asset)
            if cloud is not None:
                return cloud
            return extract_docx(self._file_bytes(asset))
        if source.source_type == SourceType.PDF.value:
            cloud = self._zai_file_payload(source, asset)
            if cloud is not None:
                return cloud
            derived = self.extracted_root / str(run_id)
            return extract_pdf(self._file_bytes(asset), self.max_pdf_pages, self.ocr_image, derived)
        if source.source_type == SourceType.IMAGE.value:
            cloud = self._zai_file_payload(source, asset)
            if cloud is not None:
                return cloud
            suffix = Path(asset.original_filename).suffix if asset else ""
            return extract_image(self._file_bytes(asset), suffix, self.ocr_image)
        if source.source_type == SourceType.URL.value:
            if not source.original_url and not source.canonical_url:
                raise ValueError("URL source has no address")
            renderer = self._browser_renderer
            owns_renderer = False
            if renderer is None and self.web_browser_fallback_enabled:
                renderer = PlaywrightBrowserRenderer(
                    timeout_seconds=self.web_browser_timeout_seconds,
                    settle_ms=self.web_browser_settle_ms,
                    max_html_bytes=self.web_max_bytes,
                    resolver=self.resolver,
                )
                owns_renderer = True
            try:
                return extract_web_with_fallback(
                    source.canonical_url or source.original_url or "",
                    self.web_timeout,
                    self.web_max_bytes,
                    self.web_max_redirects,
                    client=self.http_client,
                    resolver=self.resolver,
                    browser_fallback_enabled=self.web_browser_fallback_enabled,
                    browser_renderer=renderer,
                )
            finally:
                if owns_renderer and renderer is not None:
                    renderer.close()
        raise ValueError(f"UNSUPPORTED_SOURCE_TYPE:{source.source_type}")

    def _zai_file_payload(self, source: SourceItem, asset: SourceAsset | None) -> ExtractionPayload | None:
        if not self.zai_file_parser_enabled or source.privacy_level == "SENSITIVE":
            return None
        if self.zai_file_parser is None:
            raise RuntimeError("ZAI_FILE_PARSER_NOT_CONFIGURED")
        if asset is None:
            raise RuntimeError("FILE_MISSING")
        return self.zai_file_parser.parse(self._file_bytes(asset), asset.original_filename)

    def add_user_text_supplement(self, source_id: uuid.UUID, text: str) -> ExtractionRun:
        from app.services.extraction.x_tweet import is_x_status_url

        source = self.session.get(SourceItem, source_id)
        if source is None:
            raise LookupError("SOURCE_NOT_FOUND")
        if source.source_type != SourceType.URL.value or not is_x_status_url(source.original_url or ""):
            raise ValueError("TEXT_SUPPLEMENT_X_ONLY")
        ensure_text_acceptable(text, get_settings().max_upload_size_bytes)
        active = self.session.scalar(
            select(ExtractionRun).where(
                ExtractionRun.source_item_id == source_id,
                ExtractionRun.status.in_((ExtractionStatus.PENDING.value, ExtractionStatus.RUNNING.value)),
            )
        )
        if active is not None:
            raise RuntimeError("EXTRACTION_IN_PROGRESS")
        now = datetime.now(timezone.utc)
        run = ExtractionRun(
            id=uuid.uuid4(),
            source_item_id=source.id,
            source_asset_id=None,
            status=ExtractionStatus.RUNNING.value,
            trigger="USER_SUPPLEMENT",
            extractor_type="USER_PROVIDED_TEXT",
            extractor_version="user-supplement-v1",
            is_current=False,
            created_at=now,
            updated_at=now,
        )
        self.session.add(run)
        self.session.add(
            IngestionRecord(
                id=uuid.uuid4(),
                source_item_id=source.id,
                ingestion_type=IngestionType.TEXT_SUPPLEMENT.value,
                origin="USER_PROVIDED",
                original_input=text,
                collected_at=now,
                duplicate_detected=False,
                duplicate_reason=None,
                status=IngestionStatus.STORED.value,
                created_at=now,
            )
        )
        payload = ExtractionPayload(
            extractor_type="USER_PROVIDED_TEXT",
            extractor_version="user-supplement-v1",
            title="用户补充的 X 原文",
            blocks=[ExtractedBlock(ChunkType.PARAGRAPH.value, text, [], {"provenance": "USER_PROVIDED"})],
            metadata={
                "provenance": "USER_PROVIDED",
                "requested_url": source.original_url,
                "content_completeness": "user_supplied",
                "untrusted_content": True,
            },
            status=ExtractionStatus.SUCCEEDED.value,
        )
        self._persist(run, source, None, payload, enqueue_followups=False)
        self._enqueue_index(source.id)
        self.session.refresh(run)
        return run

    def _persist(
        self,
        run: ExtractionRun,
        source: SourceItem,
        asset: SourceAsset | None,
        payload: ExtractionPayload,
        *,
        enqueue_followups: bool = True,
    ) -> None:
        run.extractor_type = payload.extractor_type
        run.extractor_version = payload.extractor_version
        if not payload.blocks:
            self._fail(run, payload.error_code or "EXTRACTION_FAILED", payload.error_message or "提取失败。")
            return
        if payload.status == ExtractionStatus.FAILED.value:
            self._fail(run, payload.error_code or "EXTRACTION_FAILED", payload.error_message or "提取失败。")
            return
        plain = "\n\n".join(block.content for block in payload.blocks)
        chunks = chunk_blocks(payload.blocks, self.chunk_max_chars, self.chunk_overlap_chars)
        document = ExtractedDocument(
            id=uuid.uuid4(),
            extraction_run_id=run.id,
            source_item_id=source.id,
            source_asset_id=asset.id if asset else None,
            extractor_type=payload.extractor_type,
            extractor_version=payload.extractor_version,
            status=payload.status,
            title=payload.title,
            plain_text=plain,
            # Keep the legacy column for historical reads, but don't write a
            # second serialized copy: ContentChunk already stores the blocks
            # and is the production input for analysis and retrieval.
            structured_text=None,
            language=None,
            metadata_json=payload.metadata,
            content_hash=hashlib.sha256(plain.encode("utf-8")).hexdigest(),
            error_code=payload.error_code,
            error_message=payload.error_message,
        )
        self.session.add(document)
        self.session.flush()
        for sequence, block in enumerate(chunks):
            self.session.add(
                ContentChunk(
                    id=uuid.uuid4(),
                    extracted_document_id=document.id,
                    sequence=sequence,
                    heading_path=block.heading_path or None,
                    chunk_type=block.chunk_type,
                    content=block.content,
                    char_count=len(block.content),
                    token_count=max(1, len(block.content) // 4),
                    metadata_json=block.metadata,
                )
            )
        self.session.execute(
            update(ExtractionRun)
            .where(ExtractionRun.source_item_id == source.id, ExtractionRun.id != run.id)
            .values(is_current=False)
        )
        run.status = payload.status
        run.is_current = payload.status in {ExtractionStatus.SUCCEEDED.value, ExtractionStatus.PARTIAL.value}
        run.error_code = payload.error_code
        run.error_message = payload.error_message
        run.updated_at = datetime.now(timezone.utc)
        self.session.commit()
        if run.is_current and enqueue_followups:
            self._enqueue_index(source.id)
            if payload.metadata.get("content_completeness") != "metadata_only":
                self._maybe_enqueue_analysis(source.id)

    def _maybe_enqueue_analysis(self, source_id: uuid.UUID) -> None:
        try:
            import os

            from app.core.config import get_settings
            from app.services.pipeline.auto_analysis import schedule_analysis_after_extraction

            settings = get_settings()
            if os.environ.get("PYTEST_CURRENT_TEST"):
                return
            if not settings.pipeline_auto_analysis_enabled:
                return
            schedule_analysis_after_extraction(
                self.session,
                source_id,
                settings=settings,
                inline=getattr(self, "inline", False),
            )
        except Exception:
            self.session.rollback()

    def _enqueue_index(self, source_id: uuid.UUID) -> None:
        try:
            from app.core.config import get_settings
            from app.jobs.indexing import enqueue_index_source
            from app.services.retrieval.indexing import IndexingService

            settings = get_settings()
            if not IndexingService(self.session, settings).configured():
                return
            if getattr(self, "inline", False) or settings.ask_inline:
                IndexingService(self.session, settings).index_source(source_id)
            else:
                enqueue_index_source(str(source_id))
        except Exception:
            self.session.rollback()

    def _fail(self, run: ExtractionRun, code: str, message: str) -> None:
        run.status = ExtractionStatus.FAILED.value
        run.error_code = code
        run.error_message = message
        run.is_current = False
        run.updated_at = datetime.now(timezone.utc)
        self.session.commit()

    def _original_text(self, source_id: uuid.UUID) -> str:
        record = self.session.scalar(
            select(IngestionRecord)
            .where(IngestionRecord.source_item_id == source_id)
            .order_by(IngestionRecord.collected_at.asc())
        )
        return record.original_input if record else ""

    def _file_bytes(self, asset: SourceAsset | None) -> bytes:
        if asset is None:
            raise ValueError("FILE_MISSING")
        path = self.raw_root / asset.stored_path
        return path.read_bytes()

    def _file_text(self, asset: SourceAsset | None) -> str:
        return self._file_bytes(asset).decode("utf-8", errors="replace")


def _safe_error(exc: Exception) -> str:
    detail = str(exc)
    lowered = detail.lower()
    if any(word in lowered for word in ("password", "secret", "api_key", "token")):
        return type(exc).__name__
    return f"{type(exc).__name__}: {detail[:300]}"
