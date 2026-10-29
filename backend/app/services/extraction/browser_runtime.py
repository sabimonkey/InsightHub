"""Browser runtime install verification (local Chromium, no public URLs)."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.extraction.browser_renderer import create_route_handler, playwright_runtime_available

RUNTIME_PROBE_TOKEN = "INSIGHTHUB_BROWSER_RUNTIME_OK"
LOCALHOST_PROBE_URL = "http://127.0.0.1:8090/health"


@dataclass
class RuntimeProbeResult:
    ok: bool
    playwright_version: str | None
    chromium_version: str | None
    message: str


def runtime_probe() -> RuntimeProbeResult:
    if not playwright_runtime_available():
        return RuntimeProbeResult(False, None, None, "Chromium launch failed or runtime missing.")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return RuntimeProbeResult(False, None, None, "Playwright Python package missing.")

    playwright_version = None
    chromium_version = None
    html = f"""<html><body><div id="app"></div>
<script>document.getElementById('app').textContent = '{RUNTIME_PROBE_TOKEN}';</script></body></html>"""
    try:
        with sync_playwright() as playwright:
            playwright_version = playwright.chromium.version if hasattr(playwright.chromium, "version") else None
            browser = playwright.chromium.launch(headless=True)
            try:
                chromium_version = browser.version
            except Exception:
                chromium_version = None
            page = browser.new_page()
            page.set_content(html)
            page.wait_for_timeout(100)
            body = page.inner_text("body")
            page.close()
            browser.close()
    except Exception as exc:
        return RuntimeProbeResult(False, playwright_version, chromium_version, str(exc)[:300])

    if RUNTIME_PROBE_TOKEN not in body:
        return RuntimeProbeResult(False, playwright_version, chromium_version, "JS probe text missing.")
    return RuntimeProbeResult(True, playwright_version, chromium_version, "Runtime probe PASS")


def subresource_localhost_blocked_probe() -> bool:
    if not playwright_runtime_available():
        return False
    from playwright.sync_api import sync_playwright

    blocked: list[str] = []  # noqa: F841 — passed by reference to route handler
    html = f"""<html><body><script>
fetch("{LOCALHOST_PROBE_URL}").then(function(r){{return r.text();}}).then(function(t) {{
  document.body.innerText = "FETCH_OK";
}}).catch(function(){{document.body.innerText = "FETCH_BLOCKED";}});
</script></body></html>"""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        context.route("**/*", create_route_handler(resolver=None, blocked_counter=blocked))
        page = context.new_page()
        page.set_content(html)
        page.wait_for_timeout(1500)
        text = page.inner_text("body")
        page.close()
        context.close()
        browser.close()
    return "FETCH_OK" not in text and len(blocked) >= 1
