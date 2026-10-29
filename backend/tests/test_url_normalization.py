import pytest

from app.services.ingestion.errors import IngestionError
from app.services.ingestion.url_normalization import canonicalize_url


def test_strips_tracking_params_and_fragment() -> None:
    _original, canonical = canonicalize_url(
        "HTTPS://Example.COM:443/a/b?utm_source=test&id=1&fbclid=abc#section"
    )
    assert canonical == "https://example.com/a/b?id=1"


def test_x_share_param_does_not_change_identity() -> None:
    _original, with_tracking = canonicalize_url("https://x.com/example/status/123?s=46&utm_source=test")
    _original, twitter = canonicalize_url("https://twitter.com/example/status/123?s=20&t=abc")
    _original, plain = canonicalize_url("https://x.com/example/status/123")
    assert with_tracking == plain == "https://x.com/example/status/123"
    assert twitter == plain


def test_x_username_case_and_host_aliases_normalize_but_original_is_preserved() -> None:
    original, canonical = canonicalize_url("https://Twitter.com/Argona0x/Status/2110045296902164532?s=46")
    assert original == "https://Twitter.com/Argona0x/Status/2110045296902164532?s=46"
    assert canonical == "https://x.com/argona0x/status/2110045296902164532"


def test_keeps_s_param_on_other_hosts() -> None:
    _original, canonical = canonicalize_url("https://example.com/a?s=46")
    assert canonical == "https://example.com/a?s=46"


def test_rejects_invalid_urls() -> None:
    for raw in ["", "not a url", "ftp://example.com/a", "javascript:alert(1)", "http://"]:
        with pytest.raises(IngestionError) as caught:
            canonicalize_url(raw)
        assert caught.value.code == "INVALID_URL"
