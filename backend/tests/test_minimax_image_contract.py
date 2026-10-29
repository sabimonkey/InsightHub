import base64
from io import BytesIO

import httpx
import pytest
from PIL import Image

from app.core.config import get_settings
from app.services.image.minimax import MinimaxImageError, generate_image
from app.services.image.minimax_contract import MAX_PROMPT_CHARS, parse_image_generation_body


def _png_b64(width: int = 64, height: int = 64) -> str:
    img = Image.new("RGB", (width, height), color=(120, 140, 160))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _success_body(image_b64: str) -> dict:
    return {
        "base_resp": {"status_code": 0, "status_msg": "success"},
        "metadata": {"success_count": 1},
        "data": {"image_base64": [image_b64]},
    }


def test_parse_requires_array_image_base64():
    parsed = parse_image_generation_body({"base_resp": {"status_code": 0}, "metadata": {"success_count": 1}, "data": {"image_base64": "not-array"}})
    assert parsed.ok is False
    assert parsed.internal_code == "NO_IMAGE"


def test_parse_business_error_2049():
    parsed = parse_image_generation_body({"base_resp": {"status_code": 2049, "status_msg": "invalid key"}, "data": {"image_base64": []}})
    assert parsed.ok is False
    assert parsed.internal_code == "INVALID_API_KEY"


def test_parse_http200_base_resp_failure():
    parsed = parse_image_generation_body({"base_resp": {"status_code": 1008, "status_msg": "balance"}, "data": {"image_base64": [_png_b64()]}})
    assert parsed.ok is False
    assert parsed.internal_code == "INSUFFICIENT_BALANCE"


def test_generate_success_with_array_base64(monkeypatch):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    settings = get_settings().model_copy(update={"minimax_enable_fake": False, "minimax_api_key": "test-key"})
    image = _png_b64()

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode("utf-8")
        assert f'"n": 1' in body or '"n":1' in body
        return httpx.Response(200, json=_success_body(image))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = generate_image("editorial cover", settings=settings, client=client)
    assert result.ok is True
    assert result.image_bytes
    assert result.business_status == 0
    assert result.success_count == 1


def test_generate_empty_image_array(monkeypatch):
    settings = get_settings().model_copy(update={"minimax_enable_fake": False, "minimax_api_key": "test-key"})

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"base_resp": {"status_code": 0}, "metadata": {"success_count": 1}, "data": {"image_base64": []}})

    result = generate_image("x", settings=settings, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert result.ok is False
    assert result.code == "NO_IMAGE"


def test_generate_invalid_base64(monkeypatch):
    settings = get_settings().model_copy(update={"minimax_enable_fake": False, "minimax_api_key": "test-key"})

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_success_body("%%%not-base64%%%"))

    result = generate_image("x", settings=settings, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert result.ok is False
    assert result.code == "INVALID_BASE64"


def test_generate_image_too_small(monkeypatch):
    settings = get_settings().model_copy(update={"minimax_enable_fake": False, "minimax_api_key": "test-key"})
    tiny = _png_b64(8, 8)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_success_body(tiny))

    result = generate_image("x", settings=settings, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert result.ok is False
    assert result.code == "IMAGE_TOO_SMALL"


def test_prompt_over_1500_rejected(monkeypatch):
    settings = get_settings().model_copy(update={"minimax_enable_fake": False, "minimax_api_key": "test-key"})
    result = generate_image("a" * 2000, settings=settings, client=httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(500))))
    assert result.ok is False
    assert result.code == "COVER_PROMPT_TOO_LONG"


def test_rate_limit_http_429(monkeypatch):
    settings = get_settings().model_copy(update={"minimax_enable_fake": False, "minimax_api_key": "test-key"})

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"base_resp": {"status_code": 1002}})

    result = generate_image("x", settings=settings, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert result.ok is False
    assert result.code == "RATE_LIMIT"


def test_timeout_raises(monkeypatch):
    settings = get_settings().model_copy(update={"minimax_enable_fake": False, "minimax_api_key": "test-key"})

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout")

    with pytest.raises(MinimaxImageError) as exc:
        generate_image("x", settings=settings, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert exc.value.code == "TIMEOUT"
