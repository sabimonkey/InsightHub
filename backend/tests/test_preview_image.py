from app.services.extraction.preview_image import merge_preview_metadata, pick_preview_from_html, resolve_preview_url
from app.services.extraction.ssrf import SsrfError
from app.services.library_preview import library_preview_proxy_path, preview_image_from_document
from app.services.library_cover_fetch import CoverFetchError, fetch_cover_bytes
import httpx
import pytest
import uuid
from unittest.mock import MagicMock


def test_og_image_extracted_and_resolves_relative():
    html = """
    <html><head>
    <meta property="og:image" content="/images/cover.png" />
    </head><body><p>Article body long enough.</p></body></html>
    """
    url, reason = pick_preview_from_html(html, "https://example.com/post")
    assert url == "https://example.com/images/cover.png"  # resolved relative to page
    assert reason == "meta:og:image"


def test_twitter_image_extracted():
    html = '<meta name="twitter:image" content="https://example.com/tw.jpg" />'
    url, _ = pick_preview_from_html(html, "https://example.com")
    assert url == "https://example.com/tw.jpg"


def test_rejects_localhost_preview():
    assert resolve_preview_url("http://127.0.0.1/x.jpg", "https://example.com") is None


def test_merge_preview_metadata():
    html = '<meta property="og:image" content="https://example.com/a.jpg" />'
    merged = merge_preview_metadata({}, html, "https://example.com")
    assert merged["preview_image_url"] == "https://example.com/a.jpg"


def test_library_proxy_path_when_metadata_present():
    doc = MagicMock()
    doc.metadata_json = {"preview_image_url": "https://example.com/a.jpg"}
    session = MagicMock()
    path = library_preview_proxy_path(session, uuid.uuid4(), doc)
    assert path is not None
    assert "/cover-image" in path


def test_fetch_cover_blocks_bad_content_type():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-image", headers={"content-type": "text/html"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(CoverFetchError) as exc:
        fetch_cover_bytes("https://example.com/cover.jpg", client=client)
    assert exc.value.code == "COVER_CONTENT_TYPE"


def test_fetch_cover_404():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(CoverFetchError):
        fetch_cover_bytes("https://example.com/missing.jpg", client=client)
