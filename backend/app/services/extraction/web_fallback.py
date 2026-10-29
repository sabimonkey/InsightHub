"""Static-first web extraction with optional browser fallback."""

from __future__ import annotations

import httpx

from app.services.extraction.browser_renderer import BrowserRenderer, BrowserRenderResult
from app.services.extraction.types import ExtractionPayload
from app.services.extraction.web_content import payload_from_html, payload_from_rendered_html, better_payload
from app.services.extraction.web_extractor import fetch_public_page

BROWSER_FALLBACK_ERROR_CODES = frozenset({"NEEDS_BROWSER_EXTRACTION"})


def extract_web_with_fallback(
    url: str,
    timeout: float,
    max_bytes: int,
    max_redirects: int,
    *,
    client: httpx.Client | None = None,
    resolver=None,
    browser_fallback_enabled: bool = True,
    browser_renderer: BrowserRenderer | None = None,
) -> ExtractionPayload:
    from app.services.extraction.x_tweet import extract_x_tweet, is_x_status_url, payload_from_x_meta_html

    fetched = fetch_public_page(url, timeout, max_bytes, max_redirects, client, resolver)
    if is_x_status_url(url) and fetched.body:
        html = fetched.body.decode(fetched.encoding or "utf-8", errors="replace")
        x_payload = extract_x_tweet(url, timeout=timeout, client=client, resolver=resolver)
        if x_payload is not None and x_payload.status == "SUCCEEDED":
            return x_payload
        if x_payload is not None and x_payload.error_code in {"X_ACCESS_RESTRICTED", "X_TWEET_NOT_FOUND", "WEB_TIMEOUT"}:
            return x_payload
        x_metadata = x_payload.metadata if x_payload is not None else {}
        meta_payload = payload_from_x_meta_html(html, url, {**fetched.metadata, **x_metadata})
        if meta_payload is not None:
            return meta_payload
    if fetched.error_code and fetched.error_code not in BROWSER_FALLBACK_ERROR_CODES:
        return _fetch_failed(fetched)
    if fetched.body is None and fetched.error_code is None:
        return _fetch_failed(fetched)

    html = (fetched.body or b"").decode(fetched.encoding or "utf-8", errors="replace")
    static_metadata = {**fetched.metadata, "requested_url": url, "acquisition_mode": "STATIC"}
    static = payload_from_html(html, static_metadata, acquisition_mode="STATIC")

    if static.status in {"SUCCEEDED", "PARTIAL"} and static.error_code not in BROWSER_FALLBACK_ERROR_CODES:
        return static

    if static.error_code not in BROWSER_FALLBACK_ERROR_CODES:
        return static

    if not browser_fallback_enabled:
        return static

    if browser_renderer is None:
        failed = static
        failed.error_code = "BROWSER_RUNTIME_UNAVAILABLE"
        failed.error_message = "网页需要浏览器渲染，但浏览器运行时未配置。"
        failed.metadata = {**static.metadata, "browser_fallback_skipped": True}
        return failed

    render = browser_renderer.render(url)
    browser_payload = _payload_from_render(render, static.metadata)
    if static.blocks:
        return better_payload(static, browser_payload)
    return browser_payload


def _fetch_failed(fetched) -> ExtractionPayload:
    from app.services.extraction.web_extractor import _failed

    return _failed(fetched.error_code or "WEB_FETCH_FAILED", fetched.error_message or "获取网页失败。", fetched.metadata)


def _payload_from_render(render: BrowserRenderResult, static_metadata: dict) -> ExtractionPayload:
    if render.error_code:
        from app.services.extraction.web_content import _failed

        metadata = {
            **static_metadata,
            "acquisition_mode": "BROWSER",
            "fallback_reason": "NEEDS_BROWSER_EXTRACTION",
            "requested_url": render.requested_url,
            "final_url": render.final_url,
            "render_duration_ms": render.render_duration_ms,
            "blocked_request_count": render.blocked_request_count,
            **render.metadata,
        }
        return _failed(render.error_code, render.error_message or "浏览器提取失败。", metadata)

    assert render.html is not None
    metadata = {
        **static_metadata,
        "requested_url": render.requested_url,
        "final_url": render.final_url or render.requested_url,
        "render_duration_ms": render.render_duration_ms,
        "blocked_request_count": render.blocked_request_count,
        **{k: v for k, v in render.metadata.items() if k != "inner_text"},
    }
    inner_text = render.metadata.get("inner_text")
    return payload_from_rendered_html(
        render.html,
        metadata,
        inner_text_fallback=inner_text if isinstance(inner_text, str) else None,
        extra_metadata={"browser_engine": render.metadata.get("browser_engine", "playwright-chromium")},
    )
