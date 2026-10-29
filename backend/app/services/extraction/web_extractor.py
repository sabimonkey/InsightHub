from urllib.parse import urljoin

import httpx

from app.services.extraction.ssrf import SsrfError, assert_public_http_url
from app.services.extraction.types import ExtractionPayload
from app.services.extraction.web_content import WEB_VERSION, payload_from_html
from app.services.extraction.enums import ExtractorType

REDIRECT_STATUSES = {301, 302, 303, 307, 308}


def extract_web(url: str, timeout: float, max_bytes: int, max_redirects: int, client: httpx.Client | None = None, resolver=None) -> ExtractionPayload:
    fetched = fetch_public_page(url, timeout, max_bytes, max_redirects, client, resolver)
    if fetched.error_code:
        return _failed(fetched.error_code, fetched.error_message or "获取网页失败。", fetched.metadata)
    text = (fetched.body or b"").decode(fetched.encoding or "utf-8", errors="replace")
    metadata = {**fetched.metadata, "requested_url": url, "acquisition_mode": "STATIC"}
    return payload_from_html(text, metadata, acquisition_mode="STATIC")


class PublicFetch:
    def __init__(self, metadata: dict, body: bytes | None, encoding: str | None, error_code: str | None, error_message: str | None) -> None:
        self.metadata = metadata
        self.body = body
        self.encoding = encoding
        self.error_code = error_code
        self.error_message = error_message


def fetch_public_page(url: str, timeout: float, max_bytes: int, max_redirects: int, client: httpx.Client | None = None, resolver=None) -> PublicFetch:
    """Stream the response and stop as soon as the byte limit is crossed."""
    owns_client = client is None
    http = client or httpx.Client(timeout=timeout, follow_redirects=False)
    try:
        current = assert_public_http_url(url, resolver)
        for _hop in range(max_redirects + 1):
            with http.stream("GET", current, headers={"User-Agent": "InsightHub/0.2"}) as response:
                if response.status_code in REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    if not location:
                        return _consume_stream(response, current, max_bytes)
                    current = assert_public_http_url(urljoin(str(response.url) or current, location), resolver)
                    continue
                return _consume_stream(response, current, max_bytes)
        return PublicFetch({"final_url": current}, None, None, "WEB_TOO_MANY_REDIRECTS", "重定向次数超过限制。")
    except SsrfError as exc:
        return PublicFetch({}, None, None, exc.code, exc.message)
    except httpx.TimeoutException:
        return PublicFetch({}, None, None, "WEB_TIMEOUT", "获取网页超时。")
    finally:
        if owns_client:
            http.close()


def _consume_stream(response: httpx.Response, current: str, max_bytes: int) -> PublicFetch:
    content_type = response.headers.get("content-type", "")
    metadata = {
        "final_url": str(response.url) if response.url else current,
        "http_status": response.status_code,
        "content_type": content_type,
        "fetch_time": response.headers.get("date"),
        "untrusted_content": True,
    }
    if response.status_code >= 400:
        return PublicFetch(metadata, None, response.encoding, "WEB_HTTP_ERROR", f"HTTP {response.status_code}")
    declared = _declared_length(response)
    if declared is not None and declared > max_bytes:
        return PublicFetch(metadata, None, response.encoding, "WEB_RESPONSE_TOO_LARGE", "网页响应超过大小限制。")
    try:
        body = _read_limited(response, max_bytes)
    except _TooLarge:
        return PublicFetch(metadata, None, response.encoding, "WEB_RESPONSE_TOO_LARGE", "网页响应超过大小限制。")
    return PublicFetch(metadata, body, response.encoding, None, None)


def _declared_length(response: httpx.Response) -> int | None:
    raw = response.headers.get("content-length")
    if raw is None or raw.strip() == "":
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def _read_limited(response: httpx.Response, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise _TooLarge()
        chunks.append(chunk)
    return b"".join(chunks)


class _TooLarge(Exception):
    pass


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
