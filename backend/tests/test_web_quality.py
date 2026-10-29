from app.services.extraction.web_content import payload_from_html
from app.services.extraction.web_quality import assess_web_extraction, static_shell_needs_browser


def test_short_real_text_still_succeeds():
    html = "<html><body><p>This is a legitimate short note with enough letters.</p></body></html>"
    payload = payload_from_html(html, {"requested_url": "https://example.com/a", "final_url": "https://example.com/a"})
    assert payload.status == "SUCCEEDED"


def test_x_nav_shell_triggers_browser_need():
    blocks = ["Home", "Explore", "Notifications", "Messages", "Grok", "Premium", "Post", "More"]
    assert static_shell_needs_browser(blocks, 2, "https://x.com/user/status/1", "<html><script></script></html>") is True


def test_quotes_stale_static_shell_needs_browser():
    html = """<html><head><title>Quotes</title></head><body>
    <div id="app"></div><nav>Quotes to Scrape Login</nav>
    <script>window.__INITIAL__={};</script></body></html>"""
    assessment = assess_web_extraction("https://quotes.toscrape.com/js/", html, ["Quotes to Scrape", "Login"], 1)
    assert assessment.needs_browser is True


def test_challenge_page_fails_without_browser_bypass():
    html = "<html><body>Sign in to X to continue. Sign in to X now.</body></html>"
    payload = payload_from_html(html, {"requested_url": "https://x.com/foo/status/1"})
    assert payload.status == "FAILED"
    assert payload.error_code == "WEB_AUTH_OR_CHALLENGE"
