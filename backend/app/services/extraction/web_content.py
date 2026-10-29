"""Parse fetched or rendered HTML into extraction blocks (shared by static and browser paths)."""

from html.parser import HTMLParser

from app.services.extraction.enums import ChunkType, ExtractorType
from app.services.extraction.types import ExtractedBlock, ExtractionPayload
from app.services.extraction.preview_image import merge_preview_metadata
from app.services.extraction.web_quality import assess_web_extraction, static_shell_needs_browser as _quality_needs_browser

WEB_VERSION = "web-v1"
MIN_VISIBLE_CHARS = 40


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.blocks: list[str] = []
        self._skip = 0
        self._capture_title = False
        self._current: list[str] = []
        self.script_count = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
            if tag == "script":
                self.script_count += 1
        if tag == "title":
            self._capture_title = True
        if tag in {"p", "h1", "h2", "h3", "h4", "li", "tr", "br"}:
            self._flush()

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        if tag == "title":
            self._capture_title = False
        if tag in {"p", "h1", "h2", "h3", "h4", "li", "tr"}:
            self._flush()

    def handle_data(self, data):
        if self._skip:
            return
        if self._capture_title:
            self.title_parts.append(data)
        else:
            self._current.append(data)

    def _flush(self) -> None:
        text = " ".join(part.strip() for part in self._current if part.strip()).strip()
        self._current = []
        if text:
            self.blocks.append(text)

    def finish(self) -> None:
        self._flush()


def parse_visible_html(html: str) -> tuple[str | None, list[str], int]:
    parser = _VisibleTextParser()
    parser.feed(html)
    parser.finish()
    title = " ".join(parser.title_parts).strip() or None
    return title, parser.blocks, parser.script_count


def visible_text_length(blocks: list[str]) -> int:
    return len("\n\n".join(blocks).strip())


def static_shell_needs_browser(blocks: list[str], script_count: int, url: str = "", html: str = "") -> bool:
    return _quality_needs_browser(blocks, script_count, url, html)


def blocks_from_paragraphs(paragraphs: list[str]) -> list[ExtractedBlock]:
    return [ExtractedBlock(ChunkType.PARAGRAPH.value, paragraph, [], {}) for paragraph in paragraphs]


def payload_from_html(
    html: str,
    fetch_metadata: dict,
    *,
    acquisition_mode: str = "STATIC",
    fallback_reason: str | None = None,
    extra_metadata: dict | None = None,
) -> ExtractionPayload:
    title, paragraphs, script_count = parse_visible_html(html)
    visible = "\n\n".join(paragraphs).strip()
    metadata = {**fetch_metadata, "acquisition_mode": acquisition_mode, "untrusted_content": True}
    if fallback_reason:
        metadata["fallback_reason"] = fallback_reason
    if extra_metadata:
        metadata.update(extra_metadata)

    requested_url = str(fetch_metadata.get("requested_url") or fetch_metadata.get("final_url") or "")
    metadata = merge_preview_metadata(metadata, html, requested_url or None)
    if not metadata.get("preview_image_url"):
        metadata["preview_image_missing"] = True
    quality = assess_web_extraction(requested_url, html, paragraphs, script_count)

    if quality.challenge:
        payload = _failed(quality.reason_code or "WEB_AUTH_OR_CHALLENGE", quality.user_message or "无法读取页面正文。", metadata)
        payload.title = title
        return payload

    if quality.needs_browser or static_shell_needs_browser(paragraphs, script_count, requested_url, html):
        payload = _failed("NEEDS_BROWSER_EXTRACTION", "页面依赖脚本，普通 HTTP 提取没有得到正文。", metadata)
        payload.title = title
        return payload

    if not visible and script_count:
        payload = _failed("NEEDS_BROWSER_EXTRACTION", "页面依赖脚本，普通 HTTP 提取没有得到正文。", metadata)
        payload.title = title
        return payload

    if quality.low_quality and _is_short_only(visible):
        payload = _failed("WEB_EXTRACTION_LOW_QUALITY", "提取到的正文质量不足。", metadata)
        payload.title = title
        return payload

    blocks = blocks_from_paragraphs(paragraphs)
    return ExtractionPayload(
        extractor_type=ExtractorType.WEB.value,
        extractor_version=WEB_VERSION,
        title=title,
        blocks=blocks,
        metadata=metadata,
        status="SUCCEEDED" if visible else "FAILED",
        error_code=None if visible else "WEB_EMPTY",
        error_message=None if visible else "没有提取到正文。",
    )


def payload_from_rendered_html(
    html: str,
    base_metadata: dict,
    *,
    inner_text_fallback: str | None = None,
    extra_metadata: dict | None = None,
) -> ExtractionPayload:
    payload = payload_from_html(
        html,
        base_metadata,
        acquisition_mode="BROWSER",
        fallback_reason="NEEDS_BROWSER_EXTRACTION",
        extra_metadata=extra_metadata,
    )
    if payload.status != "FAILED" or payload.error_code != "WEB_EMPTY":
        return payload
    if not inner_text_fallback:
        return payload
    cleaned = _clean_inner_text(inner_text_fallback)
    if len(cleaned) < MIN_VISIBLE_CHARS:
        failed = _failed("BROWSER_RENDERED_NO_CONTENT", "浏览器渲染后仍无法提取正文。", payload.metadata)
        failed.title = payload.title
        return failed
    blocks = [ExtractedBlock(ChunkType.PARAGRAPH.value, cleaned, [], {"inner_text_fallback": True})]
    return ExtractionPayload(
        extractor_type=ExtractorType.WEB.value,
        extractor_version=WEB_VERSION,
        title=payload.title,
        blocks=blocks,
        metadata={**payload.metadata, "inner_text_fallback": True},
        status="SUCCEEDED",
        error_code=None,
        error_message=None,
    )


def _clean_inner_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    collapsed: list[str] = []
    previous = None
    for line in lines:
        if not line:
            continue
        if line == previous:
            continue
        collapsed.append(line)
        previous = line
    return "\n\n".join(collapsed).strip()


def _is_short_only(visible: str) -> bool:
    return 0 < len(visible.strip()) < MIN_VISIBLE_CHARS


def _failed(code: str, message: str, metadata: dict) -> ExtractionPayload:
    return ExtractionPayload(
        extractor_type=ExtractorType.WEB.value,
        extractor_version=WEB_VERSION,
        title=None,
        blocks=[],
        metadata=metadata,
        status="FAILED",
        error_code=code,
        error_message=message,
    )


def better_payload(static: ExtractionPayload, browser: ExtractionPayload) -> ExtractionPayload:
    """Keep static partial content when browser extraction is worse."""
    static_len = visible_text_length([b.content for b in static.blocks])
    browser_len = visible_text_length([b.content for b in browser.blocks])
    if browser.status in {"SUCCEEDED", "PARTIAL"} and browser_len >= static_len:
        return browser
    if static.blocks and static_len > 0:
        merged = ExtractionPayload(
            extractor_type=static.extractor_type,
            extractor_version=static.extractor_version,
            title=static.title or browser.title,
            blocks=static.blocks,
            metadata={
                **static.metadata,
                "browser_attempt_failed": True,
                "browser_error_code": browser.error_code,
            },
            status="PARTIAL",
            error_code=browser.error_code,
            error_message=browser.error_message,
        )
        return merged
    return browser
