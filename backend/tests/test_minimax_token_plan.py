import base64
from io import BytesIO

import httpx
import pytest
from PIL import Image

from app.core.config import get_settings
from app.services.image.minimax import MinimaxImageError, generate_image, query_token_plan_remains


def _plan(interval=100, weekly=100, interval_status=1, weekly_status=1):
    return {
        "model_remains": [{
            "remains_time": 60,
            "current_interval_usage_count": 3,
            "current_weekly_usage_count": 8,
            "weekly_remains_time": 600,
            "current_interval_status": interval_status,
            "current_interval_remaining_percent": interval,
            "current_weekly_status": weekly_status,
            "current_weekly_remaining_percent": weekly,
        }]
    }


def _mock(status, body=None):
    return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body or {})))


def test_token_plan_success_reports_shared_quota_percent_without_calling_it_image_count():
    client = _mock(200, _plan())
    result = query_token_plan_remains("secret-test-key", client=client)
    assert result["status"] == "AVAILABLE"
    assert result["current_interval_usage_count"] == 3
    assert result["weekly_remaining_percent"] == 100
    assert result["quota_unit"] == "shared_token_plan_percentage"
    client.close()


def test_token_plan_auth_failure_is_explicit():
    client = _mock(401, {"error": "unauthorized"})
    result = query_token_plan_remains("secret-test-key", client=client)
    assert result == {"status": "AUTH_FAILED", "code": "TOKEN_PLAN_AUTH_FAILED", "http_status": 401}
    client.close()


def test_token_plan_unsupported_endpoint_is_explicit():
    client = _mock(404)
    result = query_token_plan_remains("secret-test-key", client=client)
    assert result["status"] == "UNSUPPORTED"
    assert result["code"] == "TOKEN_PLAN_ENDPOINT_UNSUPPORTED"
    client.close()


def test_token_plan_exhaustion_blocks_as_unavailable():
    client = _mock(200, _plan(interval=0, weekly=50))
    result = query_token_plan_remains("secret-test-key", client=client)
    assert result["status"] == "EXHAUSTED"
    assert result["code"] == "TOKEN_PLAN_QUOTA_EXHAUSTED"
    client.close()


def test_token_plan_inactive_window_is_not_treated_as_available():
    client = _mock(200, _plan(interval_status=0))
    result = query_token_plan_remains("secret-test-key", client=client)
    assert result["status"] == "INACTIVE"
    client.close()


def test_quota_failure_blocks_image_endpoint_before_generation(monkeypatch):
    monkeypatch.setattr("app.services.image.minimax._resolved_minimax_key", lambda *_args: "vault-test-key")
    monkeypatch.setattr("app.services.image.minimax.query_token_plan_remains", lambda *_args, **_kwargs: {"status": "EXHAUSTED", "code": "TOKEN_PLAN_QUOTA_EXHAUSTED"})
    calls = []
    client = httpx.Client(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(500)))
    with pytest.raises(MinimaxImageError) as exc:
        generate_image("cover", settings=get_settings().model_copy(update={"minimax_enable_fake": False}), client=client, session=object())
    assert exc.value.code == "TOKEN_PLAN_QUOTA_EXHAUSTED"
    assert calls == []
    client.close()


def test_production_resolution_does_not_fall_back_to_legacy_environment_key(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "legacy-paygo-test-key")
    monkeypatch.setattr("app.services.image.minimax.read_vault_secret", lambda *_args: None)
    with pytest.raises(MinimaxImageError) as exc:
        generate_image("cover", settings=get_settings().model_copy(update={"minimax_enable_fake": False}), session=object())
    assert exc.value.code == "VAULT_CREDENTIAL_REQUIRED"


def test_valid_quota_preflight_proceeds_to_image_01_once(monkeypatch):
    image = Image.new("RGB", (64, 64), color=(20, 50, 80))
    output = BytesIO()
    image.save(output, format="PNG")
    image_b64 = base64.b64encode(output.getvalue()).decode("ascii")
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.method == "GET":
            return httpx.Response(200, json=_plan())
        return httpx.Response(200, json={"base_resp": {"status_code": 0}, "metadata": {"success_count": 1}, "data": {"image_base64": [image_b64]}})
    monkeypatch.setattr("app.services.image.minimax._resolved_minimax_key", lambda *_args: "vault-test-key")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = generate_image("cover", settings=get_settings().model_copy(update={"minimax_enable_fake": False}), client=client, session=object())
    assert result.ok
    assert calls == ["/v1/token_plan/remains", "/v1/image_generation"]
    client.close()
