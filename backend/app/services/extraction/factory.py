"""Construct ExtractionService with shared settings wiring."""

from sqlalchemy.orm import Session

from app.core.config import Settings
from typing import TYPE_CHECKING

from app.services.extraction.browser_renderer import PlaywrightBrowserRenderer
from app.services.extraction.zai_file_parser import ZaiFileParser

if TYPE_CHECKING:
    from app.services.extraction.service import ExtractionService


def build_extraction_service(
    session: Session,
    settings: Settings,
    *,
    inline: bool | None = None,
    enqueue=None,
    http_client=None,
    resolver=None,
    browser_renderer=None,
):
    from app.services.extraction.service import ExtractionService

    file_parser = None
    if settings.zai_file_parser_enabled:
        from app.services.llm.credential_resolver import resolve_api_key

        key = resolve_api_key("ZAI", "ZAI_API_KEY", settings, session).value
        file_parser = ZaiFileParser(api_key=key) if key else None
    return ExtractionService(
        session,
        settings.raw_storage_path(),
        settings.extracted_storage_path(),
        inline=inline if inline is not None else settings.extraction_inline,
        chunk_max_chars=settings.chunk_max_chars,
        chunk_overlap_chars=settings.chunk_overlap_chars,
        max_pdf_pages=settings.max_pdf_pages,
        web_timeout=settings.web_fetch_timeout_seconds,
        web_max_bytes=settings.web_fetch_max_bytes,
        web_max_redirects=settings.web_fetch_max_redirects,
        web_browser_fallback_enabled=settings.web_browser_fallback_enabled,
        web_browser_timeout_seconds=settings.web_browser_timeout_seconds,
        web_browser_settle_ms=settings.web_browser_settle_ms,
        enqueue=enqueue,
        http_client=http_client,
        resolver=resolver,
        browser_renderer=browser_renderer,
        zai_file_parser=file_parser,
        zai_file_parser_enabled=settings.zai_file_parser_enabled,
    )


def create_browser_renderer(
    *,
    timeout_seconds: float,
    settle_ms: int,
    max_html_bytes: int,
    resolver=None,
) -> PlaywrightBrowserRenderer:
    return PlaywrightBrowserRenderer(
        timeout_seconds=timeout_seconds,
        settle_ms=settle_ms,
        max_html_bytes=max_html_bytes,
        resolver=resolver,
    )


def browser_renderer_from_settings(settings: Settings, resolver=None) -> PlaywrightBrowserRenderer | None:
    if not settings.web_browser_fallback_enabled:
        return None
    return create_browser_renderer(
        timeout_seconds=settings.web_browser_timeout_seconds,
        settle_ms=settings.web_browser_settle_ms,
        max_html_bytes=settings.web_fetch_max_bytes,
        resolver=resolver,
    )
