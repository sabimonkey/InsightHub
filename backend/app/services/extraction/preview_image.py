"""Extract and normalize social/article preview images from HTML."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from app.services.extraction.ssrf import SsrfError, assert_public_http_url

_META_PROPERTY = re.compile(
    r'<meta\s+(?:[^>]*?\s)?(?:property|name)\s*=\s*["\']([^"\']+)["\'][^>]*?\scontent\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_META_CONTENT_FIRST = re.compile(
    r'<meta\s+(?:[^>]*?\s)?content\s*=\s*["\']([^"\']+)["\'][^>]*?\s(?:property|name)\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)

_PREVIEW_KEYS = (
    "og:image",
    "og:image:url",
    "twitter:image",
    "twitter:image:src",
    "twitter:image0",
)

_REJECT_FRAGMENTS = (
    "favicon",
    "sprite",
    "avatar",
    "profile_images",
    "profile-pic",
    "pixel",
    "tracking",
    "analytics",
    "badge",
    "emoji",
    "spacer",
    "1x1",
    "adsystem",
    "doubleclick",
)


class _LinkImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.images: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag != "img":
            return
        mapping = {k.lower(): v for k, v in attrs if isinstance(v, str)}
        src = mapping.get("src") or mapping.get("data-src")
        if src:
            self.images.append(src.strip())


def _meta_tags(html: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for match in _META_PROPERTY.finditer(html):
        key, value = match.group(1).strip().lower(), match.group(2).strip()
        found[key] = value
    for match in _META_CONTENT_FIRST.finditer(html):
        value, key = match.group(1).strip(), match.group(2).strip().lower()
        found.setdefault(key, value)
    return found


def _looks_like_bad_cover(url: str) -> bool:
    lowered = url.lower()
    if any(part in lowered for part in _REJECT_FRAGMENTS):
        return True
    path = urlsplit(url).path.lower()
    if path.endswith((".ico", ".svg")):
        return True
    if "logo" in path and "og" not in lowered:
        return True
    return False


def resolve_preview_url(raw: str | None, page_url: str | None) -> str | None:
    if not raw or not isinstance(raw, str):
        return None
    candidate = raw.strip()
    if not candidate:
        return None
    base = page_url or ""
    absolute = urljoin(base, candidate) if base else candidate
    try:
        assert_public_http_url(absolute)
    except SsrfError:
        return None
    parts = urlsplit(absolute)
    if parts.scheme.lower() not in {"http", "https"}:
        return None
    if _looks_like_bad_cover(absolute):
        return None
    if parts.scheme.lower() == "https":
        return absolute
    if parts.scheme.lower() == "http":
        host = (parts.hostname or "").lower()
        if host.endswith(("twimg.com", "githubusercontent.com", "github.com")):
            return absolute
    return None


def pick_preview_from_html(html: str, page_url: str | None) -> tuple[str | None, str | None]:
    """Return (url, reason_code). reason_code documents selection path."""
    meta = _meta_tags(html)
    for key in _PREVIEW_KEYS:
        url = resolve_preview_url(meta.get(key), page_url)
        if url:
            return url, f"meta:{key}"
    link_match = re.search(
        r'<link[^>]+rel=["\']image_src["\'][^>]+href=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if link_match:
        url = resolve_preview_url(link_match.group(1), page_url)
        if url:
            return url, "link:image_src"
    parser = _LinkImageParser()
    try:
        parser.feed(html)
    except Exception:
        parser.images = []
    for src in parser.images[:12]:
        url = resolve_preview_url(src, page_url)
        if url:
            return url, "img:article"
    return None, None


def merge_preview_metadata(metadata: dict, html: str, page_url: str | None) -> dict:
    url, reason = pick_preview_from_html(html, page_url)
    if not url:
        return metadata
    merged = {**metadata, "preview_image_url": url, "preview_image_reason": reason}
    merged["og_image"] = url
    return merged
