"""Opt-in smoke: real public JS-heavy page through production extraction pipeline."""

from __future__ import annotations

import os
import time
import httpx

# Isolate smoke sources from USER collection list.
os.environ["INSIGHTHUB_SYSTEM_SCOPE"] = "AUTOMATION_TEST"

from app.core.config import get_settings  # noqa: E402
from app.db.session import get_sessionmaker  # noqa: E402
from app.models.extraction import ContentChunk, ExtractedDocument  # noqa: E402
from app.models.source_item import SourceItem  # noqa: E402
from app.services.extraction.browser_renderer import PlaywrightBrowserRenderer, playwright_runtime_available  # noqa: E402
from app.services.extraction.enums import ExtractionTrigger  # noqa: E402
from app.services.extraction.factory import build_extraction_service  # noqa: E402
from app.services.extraction.web_extractor import extract_web  # noqa: E402
from app.services.ingestion.service import IngestionService  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

# quotes.toscrape.com/js static shell now exceeds 40 chars (nav only) — ORIGINAL_SMOKE_SOURCE_STALE.
PRIMARY_SMOKE_URL = "https://demo.playwright.dev/api-mocking"
STALE_SMOKE_URL = "https://quotes.toscrape.com/js/"
CONTENT_MARKERS = ("Strawberry", "Banana", "Render a List of Fruits")


def main() -> int:
    get_settings.cache_clear()
    settings = get_settings()
    url = PRIMARY_SMOKE_URL

    if not playwright_runtime_available():
        print("BROWSER_RUNTIME_MISSING")
        return 2

    session = get_sessionmaker()()
    user_sources_before = session.scalar(
        select(func.count()).select_from(SourceItem).where(SourceItem.system_scope == "USER")
    )
    client = httpx.Client(timeout=25, follow_redirects=False)
    static_started = time.perf_counter()
    static = extract_web(url, 25, 5_000_000, 5, client)
    static_ms = int((time.perf_counter() - static_started) * 1000)
    print(f"smoke_url={url}")
    print(f"static_status={static.status} static_error={static.error_code} static_ms={static_ms}")

    if static.error_code != "NEEDS_BROWSER_EXTRACTION":
        print("ORIGINAL_SMOKE_SOURCE_STALE: static path did not require browser")
        return 1

    renderer = PlaywrightBrowserRenderer(timeout_seconds=25, settle_ms=1500, max_html_bytes=5_000_000)
    fallback_started = time.perf_counter()
    try:
        ingestion = IngestionService(session, settings.raw_storage_path(), settings.max_upload_size_bytes)
        created = ingestion.ingest_url(url)
        assert created.source_item.system_scope == "AUTOMATION_TEST"
        service = build_extraction_service(
            session,
            settings,
            inline=True,
            http_client=client,
            browser_renderer=renderer,
        )
        run = service.schedule(created.source_item.id, ExtractionTrigger.MANUAL.value, force=True)
    finally:
        renderer.close()
        client.close()
    fallback_ms = int((time.perf_counter() - fallback_started) * 1000)

    document = session.scalar(select(ExtractedDocument).where(ExtractedDocument.extraction_run_id == run.id))
    chunks = list(
        session.scalars(select(ContentChunk).where(ContentChunk.extracted_document_id == document.id)).all()
        if document
        else []
    )
    user_sources_after = session.scalar(
        select(func.count()).select_from(SourceItem).where(SourceItem.system_scope == "USER")
    )

    if document is None:
        print(f"SMOKE_FAIL run_status={run.status} error={run.error_code}")
        session.close()
        return 1

    meta = document.metadata_json or {}
    plain = document.plain_text or ""
    chars = len(plain)
    print(f"final_status={run.status} mode={meta.get('acquisition_mode')} fallback_reason={meta.get('fallback_reason')}")
    print(f"final_url={meta.get('final_url')} render_duration_ms={meta.get('render_duration_ms')}")
    print(f"rendered_content_sha256={meta.get('rendered_content_sha256')} blocked_request_count={meta.get('blocked_request_count')}")
    print(f"extracted_chars={chars} chunk_count={len(chunks)} fallback_total_ms={fallback_ms}")

    if run.status not in {"SUCCEEDED", "PARTIAL"}:
        print("SMOKE_FAIL")
        session.close()
        return 1
    if meta.get("acquisition_mode") != "BROWSER":
        print("SMOKE_FAIL: expected BROWSER acquisition")
        session.close()
        return 1
    if meta.get("fallback_reason") != "NEEDS_BROWSER_EXTRACTION":
        print("SMOKE_FAIL: missing fallback_reason")
        session.close()
        return 1
    if chars < 200 or not any(marker in plain for marker in CONTENT_MARKERS):
        print("SMOKE_FAIL: rendered content not meaningful")
        session.close()
        return 1
    if user_sources_before != user_sources_after:
        print("SMOKE_FAIL: USER source count changed")
        session.close()
        return 1
    if document.extractor_version != "web-v1":
        print("SMOKE_FAIL: extractor_version drift")
        session.close()
        return 1

    print(f"stale_reference_url={STALE_SMOKE_URL}")
    print("SMOKE_PASS")
    session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
