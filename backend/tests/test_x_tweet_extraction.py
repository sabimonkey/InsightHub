import httpx

from app.services.extraction.web_fallback import extract_web_with_fallback
from app.services.extraction.x_tweet import extract_x_tweet, is_x_status_url, payload_from_x_meta_html, tweet_id_from_url

TARGET = "https://x.com/argona0x/status/2110045296902164532?s=46"
CANONICAL = "https://x.com/argona0x/status/2110045296902164532"

SYNDICATION_BODY = {
    "text": "Fixture tweet body about agent memory systems for deterministic tests.",
    "user": {"name": "argona0x", "screen_name": "argona0x"},
}


def test_tweet_id_and_url_detection():
    assert is_x_status_url(TARGET)
    assert tweet_id_from_url(TARGET) == "2110045296902164532"
    assert tweet_id_from_url(CANONICAL) == "2110045296902164532"


def _mock_client(responses: dict[str, httpx.Response]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        for prefix, response in responses.items():
            if prefix in str(request.url):
                return response
        return httpx.Response(404, json={"error": "not found"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_syndication_success():
    client = _mock_client(
        {
            "cdn.syndication.twimg.com": httpx.Response(200, json=SYNDICATION_BODY),
        }
    )
    payload = extract_x_tweet(TARGET, timeout=2, client=client, resolver=lambda _h: ["93.184.216.34"])
    assert payload is not None
    assert payload.status == "SUCCEEDED"
    assert "Fixture tweet body" in payload.blocks[0].content
    assert payload.metadata.get("acquisition_mode") == "X_SYNDICATION"


def test_access_restricted():
    client = _mock_client({"cdn.syndication.twimg.com": httpx.Response(403, text="forbidden")})
    payload = extract_x_tweet(TARGET, timeout=2, client=client, resolver=lambda _h: ["93.184.216.34"])
    assert payload is not None
    assert payload.status == "FAILED"
    assert payload.error_code == "X_ACCESS_RESTRICTED"


def test_empty_syndication_falls_back_to_oembed():
    client = _mock_client(
        {
            "cdn.syndication.twimg.com": httpx.Response(200, json={"text": ""}),
            "publish.twitter.com": httpx.Response(
                200,
                json={"html": "<blockquote><p>OEmbed tweet text for tests.</p></blockquote>", "author_name": "argona0x"},
            ),
        }
    )
    payload = extract_x_tweet(TARGET, timeout=2, client=client, resolver=lambda _h: ["93.184.216.34"])
    assert payload is not None
    assert payload.status == "SUCCEEDED"
    assert "OEmbed tweet text" in payload.blocks[0].content


def test_meta_html_extracts_og_description():
    html = (
        '<meta property="og:description" content="How to build a Second Brain that actually does the work" />'
        '<meta property="og:title" content="Argona on X" />'
    )
    payload = payload_from_x_meta_html(html, TARGET, {"http_status": 200})
    assert payload is not None
    assert payload.status == "PARTIAL"
    assert payload.error_code == "X_METADATA_ONLY"
    assert "Second Brain" in payload.blocks[0].content
    assert payload.metadata.get("acquisition_mode") == "X_META"
    assert payload.metadata.get("content_completeness") == "metadata_only"


def test_link_only_oembed_is_reported_as_incomplete_not_post_body():
    client = _mock_client(
        {
            "cdn.syndication.twimg.com": httpx.Response(200, json={}),
            "publish.twitter.com": httpx.Response(
                200,
                json={"html": '<blockquote><p><a href="https://t.co/article">https://t.co/article</a></p></blockquote>'},
            ),
        }
    )
    payload = extract_x_tweet(TARGET, timeout=2, client=client, resolver=lambda _h: ["93.184.216.34"])
    assert payload is not None
    assert payload.status == "FAILED"
    assert payload.error_code == "X_EXTRACTION_EMPTY"
    assert payload.metadata.get("oembed_link_only") is True
    assert payload.metadata.get("oembed_link") == "https://t.co/article"


def test_web_fallback_uses_x_path_before_static_html():
    html = "<html><body><div id=app></div><script></script></body></html>"
    client = _mock_client(
        {
            "cdn.syndication.twimg.com": httpx.Response(200, json=SYNDICATION_BODY),
            "x.com": httpx.Response(200, text=html, headers={"content-type": "text/html"}),
        }
    )

    payload = extract_web_with_fallback(
        TARGET,
        timeout=2,
        max_bytes=100_000,
        max_redirects=3,
        client=client,
        resolver=lambda _h: ["93.184.216.34"],
        browser_fallback_enabled=False,
    )
    assert payload.status == "SUCCEEDED"
    assert "Fixture tweet body" in payload.blocks[0].content
