"""Headless browser rendering for web extraction fallback (production Playwright adapter)."""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol
from urllib.parse import urlsplit

from app.services.extraction.ssrf import SsrfError, assert_public_http_url

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = {"http", "https"}
BLOCKED_RESOURCE_TYPES = frozenset({"websocket", "media", "font"})
CHALLENGE_PATTERNS = [
    re.compile(r"just a moment", re.I),
    re.compile(r"verify you are human", re.I),
    re.compile(r"attention required", re.I),
    re.compile(r"cf-browser-verification", re.I),
]
AUTH_PATTERNS = [
    re.compile(r"sign in to continue", re.I),
    re.compile(r"log in to continue", re.I),
]


@dataclass
class BrowserRenderResult:
    requested_url: str
    final_url: str | None
    html: str | None
    title: str | None
    error_code: str | None
    error_message: str | None
    render_duration_ms: int = 0
    blocked_request_count: int = 0
    metadata: dict = field(default_factory=dict)


class BrowserRenderer(Protocol):
    def render(self, url: str) -> BrowserRenderResult: ...

    def close(self) -> None: ...


class BrowserRenderError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def playwright_runtime_available() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception:
        return False


class PlaywrightBrowserRenderer:
    def __init__(
        self,
        *,
        timeout_seconds: float,
        settle_ms: int,
        max_html_bytes: int,
        resolver=None,
        user_agent: str | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.settle_ms = settle_ms
        self.max_html_bytes = max_html_bytes
        self.resolver = resolver
        self.user_agent = user_agent
        self._playwright = None
        self._browser = None

    def render(self, url: str) -> BrowserRenderResult:
        started = time.perf_counter()
        blocked: list[str] = []
        try:
            assert_public_http_url(url, self.resolver)
        except SsrfError as exc:
            return BrowserRenderResult(
                requested_url=url,
                final_url=None,
                html=None,
                title=None,
                error_code="BROWSER_SSRF_BLOCKED",
                error_message=exc.message,
                render_duration_ms=_elapsed_ms(started),
                blocked_request_count=0,
            )

        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError:
            return BrowserRenderResult(
                requested_url=url,
                final_url=None,
                html=None,
                title=None,
                error_code="BROWSER_RUNTIME_UNAVAILABLE",
                error_message="未安装 Playwright 浏览器运行时。",
                render_duration_ms=_elapsed_ms(started),
            )

        page = None
        context = None
        try:
            if self._playwright is None:
                self._playwright = sync_playwright().start()
                self._browser = self._playwright.chromium.launch(headless=True)
            context = self._browser.new_context(
                accept_downloads=False,
                java_script_enabled=True,
                service_workers="block",
                user_agent=self.user_agent,
            )
            context.set_default_timeout(int(self.timeout_seconds * 1000))
            context.set_default_navigation_timeout(int(self.timeout_seconds * 1000))

            context.route("**/*", create_route_handler(self.resolver, blocked))
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=int(self.timeout_seconds * 1000))
            if self.settle_ms > 0:
                page.wait_for_timeout(self.settle_ms)
            final_url = page.url
            try:
                assert_public_http_url(final_url, self.resolver)
            except SsrfError as exc:
                return BrowserRenderResult(
                    requested_url=url,
                    final_url=final_url,
                    html=None,
                    title=None,
                    error_code="BROWSER_SSRF_BLOCKED",
                    error_message=exc.message,
                    render_duration_ms=_elapsed_ms(started),
                    blocked_request_count=len(blocked),
                )
            title = page.title() or None
            html = page.content()
            if len(html.encode("utf-8")) > self.max_html_bytes:
                html = html.encode("utf-8")[: self.max_html_bytes].decode("utf-8", errors="ignore")
            challenge = _detect_challenge(html, title)
            if challenge:
                return BrowserRenderResult(
                    requested_url=url,
                    final_url=final_url,
                    html=None,
                    title=title,
                    error_code=challenge,
                    error_message="页面需要验证或登录，无法自动提取。",
                    render_duration_ms=_elapsed_ms(started),
                    blocked_request_count=len(blocked),
                )
            inner_text = None
            try:
                inner_text = page.inner_text("body")
            except PlaywrightError:
                inner_text = None
            content_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
            return BrowserRenderResult(
                requested_url=url,
                final_url=final_url,
                html=html,
                title=title,
                error_code=None,
                error_message=None,
                render_duration_ms=_elapsed_ms(started),
                blocked_request_count=len(blocked),
                metadata={
                    "browser_engine": "playwright-chromium",
                    "rendered_content_sha256": content_hash,
                    "inner_text": inner_text,
                },
            )
        except PlaywrightError as exc:
            message = str(exc)
            code = "BROWSER_NAVIGATION_TIMEOUT" if "timeout" in message.lower() else "BROWSER_RENDER_ERROR"
            return BrowserRenderResult(
                requested_url=url,
                final_url=page.url if page else None,
                html=None,
                title=None,
                error_code=code,
                error_message=message[:300],
                render_duration_ms=_elapsed_ms(started),
                blocked_request_count=len(blocked),
            )
        finally:
            if page is not None:
                page.close()
            if context is not None:
                context.close()

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None


class ScriptableBrowserRenderer:
    """Deterministic renderer for tests (no network)."""

    def __init__(self, handler: Callable[[str], BrowserRenderResult]) -> None:
        self.handler = handler
        self.calls = 0

    def render(self, url: str) -> BrowserRenderResult:
        self.calls += 1
        return self.handler(url)

    def close(self) -> None:
        return None


def create_route_handler(resolver, blocked_counter: list[str]):
    """Shared network policy for production render and runtime security probes."""

    def route_handler(route, request) -> None:
        if request.resource_type in BLOCKED_RESOURCE_TYPES:
            blocked_counter.append(request.url)
            route.abort()
            return
        if not _request_url_allowed(request.url, resolver):
            blocked_counter.append(request.url)
            route.abort("blockedbyclient")
            return
        route.continue_()

    return route_handler


def _request_url_allowed(url: str, resolver) -> bool:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme in {"data", "blob", "about"}:
        return True
    if scheme not in ALLOWED_SCHEMES:
        return False
    try:
        assert_public_http_url(url, resolver)
    except SsrfError:
        return False
    return True


def _detect_challenge(html: str, title: str | None) -> str | None:
    sample = f"{title or ''}\n{html[:4000]}"
    visible_len = len(re.sub(r"<[^>]+>", " ", sample))
    if visible_len > 800:
        return None
    lowered = sample.lower()
    for pattern in CHALLENGE_PATTERNS:
        if pattern.search(lowered):
            return "BROWSER_CHALLENGE_DETECTED"
    for pattern in AUTH_PATTERNS:
        if pattern.search(lowered):
            return "BROWSER_AUTH_REQUIRED"
    return None


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
