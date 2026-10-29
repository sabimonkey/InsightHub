"""X / Twitter status extraction helpers (fixtures-friendly, no auth)."""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

import httpx

from app.services.extraction.enums import ChunkType, ExtractorType
from app.services.extraction.ssrf import assert_public_http_url
from app.services.extraction.types import ExtractedBlock, ExtractionPayload
from app.services.extraction.web_content import WEB_VERSION
from app.services.ingestion.url_normalization import X_HOSTS

STATUS_ID_RE = re.compile(r"/status/(\d+)(?:/|$|\?)", re.I)
META_CONTENT_RE = re.compile(r'(?:property|name)="(?P<key>[^"]+)"\s+content="(?P<value>[^"]*)"', re.I)
TWEET_URL_ONLY_RE = re.compile(r"^https?://\S+$")
SYNDICATION_TEMPLATE = "https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&lang=en"
OEMBED_TEMPLATE = "https://publish.twitter.com/oembed?omit_script=1&url={url}"


def is_x_status_url(url: str) -> bool:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if host not in X_HOSTS and not host.endswith(".x.com") and not host.endswith(".twitter.com"):
        return False
    return STATUS_ID_RE.search(parts.path or "") is not None


def tweet_id_from_url(url: str) -> str | None:
    match = STATUS_ID_RE.search(urlsplit(url.strip()).path or "")
    return match.group(1) if match else None


def is_usable_tweet_text(text: str) -> bool:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if len(cleaned) < 20:
        return False
    if TWEET_URL_ONLY_RE.fullmatch(cleaned):
        return False
    return True


def payload_from_x_meta_html(html: str, url: str, fetch_metadata: dict) -> ExtractionPayload | None:
    if not html:
        return None
    values: dict[str, str] = {}
    for match in META_CONTENT_RE.finditer(html):
        key = match.group("key").lower()
        values[key] = match.group("value")
    description = values.get("og:description") or values.get("twitter:description")
    if not description or not is_usable_tweet_text(description):
        return None
    title = values.get("og:title") or values.get("twitter:title") or "X post"
    metadata = {**fetch_metadata, "requested_url": url, "acquisition_mode": "X_META", "untrusted_content": True}
    payload = _success_payload(description, title=title[:200], metadata={
        **metadata,
        "content_completeness": "metadata_only",
        "body_text_source": "x_page_meta_description",
    })
    payload.status = "PARTIAL"
    payload.error_code = "X_METADATA_ONLY"
    payload.error_message = "仅获取到 X 页面元数据文本，完整推文或关联文章正文未能公开提取。"
    return payload


def extract_x_tweet(
    url: str,
    *,
    timeout: float,
    client: httpx.Client | None,
    resolver=None,
) -> ExtractionPayload | None:
    if not is_x_status_url(url):
        return None
    tweet_id = tweet_id_from_url(url)
    if not tweet_id:
        return None
    owns = client is None
    http = client or httpx.Client(timeout=timeout, follow_redirects=True)
    metadata: dict = {"requested_url": url, "acquisition_mode": "X_SYNDICATION", "tweet_id": tweet_id}
    try:
        try:
            syndication_url = assert_public_http_url(SYNDICATION_TEMPLATE.format(tweet_id=tweet_id), resolver)
            response = http.get(syndication_url, headers={"User-Agent": "InsightHub/0.2"})
            metadata["syndication_http_status"] = response.status_code
            if response.status_code == 200:
                body = response.json()
                text = _tweet_text_from_syndication(body)
                if text and is_usable_tweet_text(text):
                    return _success_payload(text, title=_title_from_syndication(body), metadata=metadata)
                metadata["syndication_empty"] = True
            elif response.status_code in {401, 403, 404}:
                return _failed(
                    "X_ACCESS_RESTRICTED" if response.status_code in {401, 403} else "X_TWEET_NOT_FOUND",
                    "推文需要登录、不可公开访问，或已被删除。",
                    metadata,
                )
        except httpx.TimeoutException:
            return _failed("WEB_TIMEOUT", "获取 X 推文超时。", metadata)
        except (json.JSONDecodeError, httpx.HTTPError) as exc:
            metadata["syndication_error"] = type(exc).__name__

        try:
            oembed_url = assert_public_http_url(OEMBED_TEMPLATE.format(url=url.strip()), resolver)
            response = http.get(oembed_url, headers={"User-Agent": "InsightHub/0.2"})
            metadata["oembed_http_status"] = response.status_code
            if response.status_code == 200:
                body = response.json()
                text = _text_from_oembed_html(body.get("html") if isinstance(body, dict) else None)
                author = body.get("author_name") if isinstance(body, dict) else None
                if text and is_usable_tweet_text(text):
                    title = f"{author} on X" if author else "X post"
                    metadata["acquisition_mode"] = "X_OEMBED"
                    return _success_payload(text, title=title, metadata=metadata)
                if text and TWEET_URL_ONLY_RE.fullmatch(text):
                    metadata["oembed_link_only"] = True
                    metadata["oembed_link"] = text
        except httpx.TimeoutException:
            return _failed("WEB_TIMEOUT", "获取 X 推文超时。", metadata)
        except httpx.HTTPError as exc:
            metadata["oembed_error"] = type(exc).__name__

        return _failed("X_EXTRACTION_EMPTY", "页面可访问但未提取到推文正文。", metadata)
    finally:
        if owns:
            http.close()


def _tweet_text_from_syndication(body: object) -> str | None:
    if not isinstance(body, dict):
        return None
    text = body.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    legacy = body.get("legacy")
    if isinstance(legacy, dict):
        full = legacy.get("full_text")
        if isinstance(full, str) and full.strip():
            return full.strip()
    return None


def _title_from_syndication(body: object) -> str | None:
    if not isinstance(body, dict):
        return None
    user = body.get("user")
    if isinstance(user, dict):
        name = user.get("name") or user.get("screen_name")
        if isinstance(name, str) and name.strip():
            return f"{name.strip()} on X"
    return "X post"


def _text_from_oembed_html(html: str | None) -> str | None:
    if not html or not isinstance(html, str):
        return None
    match = re.search(r"<p[^>]*>(.*?)</p>", html, re.I | re.S)
    if not match:
        return None
    inner = re.sub(r"<[^>]+>", "", match.group(1))
    inner = inner.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    inner = re.sub(r"\s+", " ", inner).strip()
    return inner or None


def _success_payload(text: str, *, title: str | None, metadata: dict) -> ExtractionPayload:
    blocks = [ExtractedBlock(ChunkType.PARAGRAPH.value, text, [], {"platform": "x"})]
    return ExtractionPayload(
        extractor_type=ExtractorType.WEB.value,
        extractor_version=f"{WEB_VERSION}+x-syndication",
        title=title,
        blocks=blocks,
        metadata={**metadata, "untrusted_content": True},
        status="SUCCEEDED",
        error_code=None,
        error_message=None,
    )


def _failed(code: str, message: str, metadata: dict) -> ExtractionPayload:
    return ExtractionPayload(
        extractor_type=ExtractorType.WEB.value,
        extractor_version=f"{WEB_VERSION}+x-syndication",
        title=None,
        blocks=[],
        metadata=metadata,
        status="FAILED",
        error_code=code,
        error_message=message,
    )
