"""Fetch cover images with SSRF and size limits."""

from __future__ import annotations

import httpx

from app.services.extraction.ssrf import SsrfError, assert_public_http_url
ALLOWED_PREFIXES = ("image/jpeg", "image/png", "image/webp", "image/gif")
MAX_COVER_BYTES = 2_000_000


class CoverFetchError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def fetch_cover_bytes(url: str, *, client: httpx.Client | None = None) -> tuple[bytes, str]:
    try:
        assert_public_http_url(url)
    except SsrfError as exc:
        raise CoverFetchError(exc.code, exc.message) from exc

    owns = client is None
    http = client or httpx.Client(follow_redirects=False, timeout=httpx.Timeout(12.0))
    try:
        current = url
        for _ in range(5):
            response = http.get(current)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    break
                from urllib.parse import urljoin

                current = assert_public_http_url(urljoin(str(response.url) or current, location))
                continue
            if response.status_code >= 400:
                raise CoverFetchError("COVER_HTTP_ERROR", f"HTTP {response.status_code}")
            content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
            if content_type and not content_type.startswith(ALLOWED_PREFIXES):
                raise CoverFetchError("COVER_CONTENT_TYPE", "不支持的封面 Content-Type。")
            body = _read_limited(response, MAX_COVER_BYTES)
            if not body:
                raise CoverFetchError("COVER_EMPTY", "封面响应为空。")
            return body, content_type or "image/jpeg"
        raise CoverFetchError("COVER_TOO_MANY_REDIRECTS", "封面重定向过多。")
    except httpx.TimeoutException as exc:
        raise CoverFetchError("COVER_TIMEOUT", "获取封面超时。") from exc
    finally:
        if owns:
            http.close()


def _read_limited(response: httpx.Response, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise CoverFetchError("COVER_TOO_LARGE", "封面图片超过大小限制。")
        chunks.append(chunk)
    return b"".join(chunks)
