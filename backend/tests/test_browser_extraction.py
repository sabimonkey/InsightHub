import httpx
import pytest

from app.services.extraction.browser_renderer import BrowserRenderResult, ScriptableBrowserRenderer, _request_url_allowed
from app.services.extraction.types import ExtractedBlock, ExtractionPayload
from app.services.extraction.web_content import WEB_VERSION, better_payload, payload_from_html
from app.services.extraction.web_fallback import extract_web_with_fallback
from app.services.extraction.enums import ChunkType, ExtractorType


JS_SHELL_HTML = """<!doctype html><html><head><title>Shell</title></head>
<body><div id="app"></div>
<script>setTimeout(function(){document.getElementById('app').innerHTML=
'<article><h1>Fixture Title</h1><p>Browser rendered unique content for PILOT-04 deterministic gate.</p></article>';}, 50);</script>
</body></html>"""

RENDERED_HTML = """<!doctype html><html><head><title>Shell</title></head>
<body><div id="app"><article><h1>Fixture Title</h1>
<p>Browser rendered unique content for PILOT-04 deterministic gate.</p></article></div></body></html>"""

STATIC_GOOD_HTML = "<html><title>Ok</title><body><p>Public article text that is long enough to keep without browser.</p></body></html>"


def _public_resolver(_host: str) -> list[str]:
    return ["93.184.216.34"]


def _mock_client(html: str) -> httpx.Client:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_static_good_page_never_calls_browser():
    renderer = ScriptableBrowserRenderer(lambda _url: BrowserRenderResult("", None, None, None, "X", "x"))
    payload = extract_web_with_fallback(
        "http://example.test/page",
        timeout=2,
        max_bytes=50_000,
        max_redirects=2,
        client=_mock_client(STATIC_GOOD_HTML),
        resolver=_public_resolver,
        browser_renderer=renderer,
    )
    assert payload.status == "SUCCEEDED"
    assert renderer.calls == 0
    assert payload.metadata.get("acquisition_mode") == "STATIC"


def test_js_shell_triggers_browser_once_and_succeeds():
    renderer = ScriptableBrowserRenderer(
        lambda _url: BrowserRenderResult(
            requested_url=_url,
            final_url=_url,
            html=RENDERED_HTML,
            title="Shell",
            error_code=None,
            error_message=None,
            render_duration_ms=12,
            metadata={"browser_engine": "test"},
        )
    )
    payload = extract_web_with_fallback(
        "http://example.test/js",
        timeout=2,
        max_bytes=50_000,
        max_redirects=2,
        client=_mock_client(JS_SHELL_HTML),
        resolver=_public_resolver,
        browser_renderer=renderer,
    )
    assert renderer.calls == 1
    assert payload.status == "SUCCEEDED"
    assert payload.metadata.get("acquisition_mode") == "BROWSER"
    joined = "\n".join(block.content for block in payload.blocks)
    assert "Browser rendered unique content" in joined


def test_browser_fail_without_static_blocks_fails():
    renderer = ScriptableBrowserRenderer(
        lambda _url: BrowserRenderResult(
            requested_url=_url,
            final_url=_url,
            html=None,
            title=None,
            error_code="BROWSER_RENDER_ERROR",
            error_message="boom",
        )
    )
    payload = extract_web_with_fallback(
        "http://example.test/js",
        timeout=2,
        max_bytes=50_000,
        max_redirects=2,
        client=_mock_client(JS_SHELL_HTML),
        resolver=_public_resolver,
        browser_renderer=renderer,
    )
    assert payload.status == "FAILED"
    assert payload.error_code == "BROWSER_RENDER_ERROR"


def test_static_partial_preserved_when_browser_worse():
    static = ExtractionPayload(
        extractor_type=ExtractorType.WEB.value,
        extractor_version=WEB_VERSION,
        title="Partial",
        blocks=[ExtractedBlock(ChunkType.PARAGRAPH.value, "A" * 80, [], {})],
        metadata={"acquisition_mode": "STATIC"},
        status="PARTIAL",
        error_code=None,
        error_message=None,
    )
    browser = ExtractionPayload(
        extractor_type=ExtractorType.WEB.value,
        extractor_version=WEB_VERSION,
        title="Bad",
        blocks=[ExtractedBlock(ChunkType.PARAGRAPH.value, "short", [], {})],
        metadata={"acquisition_mode": "BROWSER"},
        status="SUCCEEDED",
        error_code=None,
        error_message=None,
    )
    merged = better_payload(static, browser)
    assert merged.status == "PARTIAL"
    assert merged.blocks[0].content == "A" * 80
    assert merged.metadata.get("browser_attempt_failed") is True


def test_feature_flag_off_skips_browser():
    renderer = ScriptableBrowserRenderer(lambda _url: BrowserRenderResult("", None, "x", None, None, None))
    payload = extract_web_with_fallback(
        "http://example.test/js",
        timeout=2,
        max_bytes=50_000,
        max_redirects=2,
        client=_mock_client(JS_SHELL_HTML),
        resolver=_public_resolver,
        browser_fallback_enabled=False,
        browser_renderer=renderer,
    )
    assert renderer.calls == 0
    assert payload.error_code == "NEEDS_BROWSER_EXTRACTION"


def test_same_extractor_for_static_and_rendered_html():
    static = payload_from_html(JS_SHELL_HTML, {"final_url": "http://example.test"})
    rendered = payload_from_html(
        RENDERED_HTML,
        {"final_url": "http://example.test"},
        acquisition_mode="BROWSER",
    )
    assert static.error_code == "NEEDS_BROWSER_EXTRACTION"
    assert rendered.status == "SUCCEEDED"
    assert rendered.blocks[0].chunk_type == ChunkType.PARAGRAPH.value


def test_subresource_localhost_blocked_by_policy():
    assert _request_url_allowed("http://127.0.0.1:8090/health", _public_resolver) is False
    assert _request_url_allowed("http://example.test/page", _public_resolver) is True
    assert _request_url_allowed("file:///etc/passwd", _public_resolver) is False


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://169.254.169.254/",
    ],
)
def test_browser_renderer_blocks_initial_ssrf(url):
    from app.services.extraction.browser_renderer import PlaywrightBrowserRenderer

    renderer = PlaywrightBrowserRenderer(timeout_seconds=2, settle_ms=0, max_html_bytes=1000, resolver=_public_resolver)
    result = renderer.render(url)
    assert result.error_code == "BROWSER_SSRF_BLOCKED"


def test_playwright_runtime_probe_executes_js():
    from app.services.extraction.browser_renderer import playwright_runtime_available
    from app.services.extraction.browser_runtime import RUNTIME_PROBE_TOKEN, runtime_probe

    if not playwright_runtime_available():
        pytest.fail("Chromium runtime required for PILOT-04 closure")
    result = runtime_probe()
    assert result.ok, result.message


def test_playwright_engine_blocks_localhost_subresource():
    from app.services.extraction.browser_renderer import playwright_runtime_available
    from app.services.extraction.browser_runtime import subresource_localhost_blocked_probe

    if not playwright_runtime_available():
        pytest.fail("Chromium runtime required for PILOT-04 closure")
    assert subresource_localhost_blocked_probe() is True


def test_browser_fallback_without_renderer_reports_unavailable():
    payload = extract_web_with_fallback(
        "http://example.test/js",
        timeout=2,
        max_bytes=50_000,
        max_redirects=2,
        client=_mock_client(JS_SHELL_HTML),
        resolver=_public_resolver,
        browser_renderer=None,
    )
    assert payload.error_code == "BROWSER_RUNTIME_UNAVAILABLE"
