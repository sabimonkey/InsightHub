import json

import httpx

from app.services.llm.capability_probe import apply_probe_capabilities, probe_deployment_capabilities
from app.services.llm.provider import OpenAICompatibleProvider
import pytest

from app.services.llm.routing import RoutingError, _check_capability
from app.services.llm.registry import ProviderSpec


def _baseline_handler(payload: dict, *, json_object: str | None = None, json_schema: str | None = None, stream: bool = True) -> httpx.Response:
    fmt = (payload.get("response_format") or {}).get("type")
    if fmt == "json_object":
        messages = payload.get("messages") or []
        if any("你好" in (m.get("content") or "") for m in messages):
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"text":"你好，世界"}'}}], "model": "probe-model"})
        if json_object == "unsupported":
            return httpx.Response(400, text="response_format json_object is not supported")
        if json_object == "503":
            return httpx.Response(503, text="overloaded")
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}], "model": "probe-model"})
    if fmt == "json_schema":
        if json_schema == "unsupported":
            return httpx.Response(400, text="json_schema unsupported parameter")
        if json_schema == "invalid":
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": false}'}}], "model": "probe-model"})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}], "model": "probe-model"})
    if payload.get("stream"):
        if not stream:
            return httpx.Response(400, text="stream unsupported")
        return httpx.Response(
            200,
            content='data: {"choices":[{"delta":{"content":"O"}}]}\n\ndata: [DONE]\n\n',
            headers={"content-type": "text/event-stream"},
        )
    messages = payload.get("messages") or []
    if any("连接正常" in (m.get("content") or "") for m in messages):
        return httpx.Response(200, json={"choices": [{"message": {"content": "连接正常"}}], "model": "probe-model"})
    return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}], "model": "probe-model"})


def _provider(handler) -> OpenAICompatibleProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAICompatibleProvider(
        provider_type="GENERIC_OPENAI_COMPATIBLE",
        base_url="https://example.invalid/v1",
        model="probe-model",
        api_key="test-credential",
        is_local=False,
        timeout=2,
        max_retries=0,
        supports_json_schema=False,
        supports_json_object=False,
        client=client,
    )


def test_json_object_supported_updates_capability():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        fmt = (payload.get("response_format") or {}).get("type")
        if fmt == "json_object":
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}], "model": "probe-model"})
        if fmt == "json_schema":
            return httpx.Response(400, text="unsupported response_format json_schema")
        if payload.get("stream"):
            return httpx.Response(200, content='data: {"choices":[{"delta":{"content":"O"}}]}\n\ndata: [DONE]\n\n', headers={"content-type": "text/event-stream"})
        messages = payload["messages"]
        if any("连接正常" in (m.get("content") or "") for m in messages):
            return httpx.Response(200, json={"choices": [{"message": {"content": "连接正常"}}], "model": "probe-model"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}], "model": "probe-model"})

    provider = _provider(handler)
    result = probe_deployment_capabilities(provider)
    assert result["overall_status"] == "PASS"
    assert result["probes"]["json_object"]["status"] == "SUPPORTED"
    caps = apply_probe_capabilities({"supports_json_object": False}, result["probes"])
    assert caps["supports_json_object"] is True


def test_json_object_unsupported_400():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        return _baseline_handler(payload, json_object="unsupported", json_schema="unsupported")

    provider = _provider(handler)
    result = probe_deployment_capabilities(provider)
    assert result["probes"]["json_object"]["status"] == "UNSUPPORTED"
    caps = apply_probe_capabilities({"supports_json_object": True}, result["probes"])
    assert caps["supports_json_object"] is False


def test_json_object_transient_503_keeps_value():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        return _baseline_handler(payload, json_object="503", json_schema="unsupported")

    provider = _provider(handler)
    result = probe_deployment_capabilities(provider)
    assert result["probes"]["json_object"]["status"] == "TRANSIENT_FAILURE"
    caps = apply_probe_capabilities({"supports_json_object": True}, result["probes"])
    assert caps["supports_json_object"] is True


def test_json_schema_supported():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        fmt = (payload.get("response_format") or {}).get("type")
        if fmt == "json_schema":
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}], "model": "probe-model"})
        if fmt == "json_object":
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}], "model": "probe-model"})
        if payload.get("stream"):
            return httpx.Response(200, content='data: {"choices":[{"delta":{"content":"O"}}]}\n\ndata: [DONE]\n\n', headers={"content-type": "text/event-stream"})
        messages = payload["messages"]
        if any("连接正常" in (m.get("content") or "") for m in messages):
            return httpx.Response(200, json={"choices": [{"message": {"content": "连接正常"}}], "model": "probe-model"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}], "model": "probe-model"})

    provider = _provider(handler)
    result = probe_deployment_capabilities(provider)
    assert result["probes"]["json_schema"]["status"] == "SUPPORTED"


def test_json_schema_invalid_output_not_supported():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        fmt = (payload.get("response_format") or {}).get("type")
        if fmt == "json_schema":
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": false}'}}], "model": "probe-model"})
        if fmt == "json_object":
            return httpx.Response(400, text="unsupported json_object")
        if payload.get("stream"):
            return httpx.Response(400, text="stream unsupported")
        messages = payload["messages"]
        if any("连接正常" in (m.get("content") or "") for m in messages):
            return httpx.Response(200, json={"choices": [{"message": {"content": "连接正常"}}], "model": "probe-model"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}], "model": "probe-model"})

    provider = _provider(handler)
    result = probe_deployment_capabilities(provider)
    assert result["probes"]["json_schema"]["status"] == "UNSUPPORTED"


def test_json_schema_explicit_unsupported():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        return _baseline_handler(payload, json_schema="unsupported")

    provider = _provider(handler)
    result = probe_deployment_capabilities(provider)
    assert result["probes"]["json_schema"]["status"] == "UNSUPPORTED"


def test_chat_failure_overall_fail():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="down")

    provider = _provider(handler)
    result = probe_deployment_capabilities(provider)
    assert result["overall_status"] == "FAIL"
    assert "json_object" not in result["probes"]


def test_zai_chat_probe_reports_reasoning_budget_exhaustion_without_mislabeling_http():
    from app.services.llm.provider import ZaiProvider

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["max_tokens"] >= 512
        assert payload["thinking"] == {"type": "enabled"}
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "length", "message": {"content": ""}}],
            "usage": {"completion_tokens": 16, "completion_tokens_details": {"reasoning_tokens": 16}},
        })

    provider = ZaiProvider(
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-5.3-flash",
        api_key="test-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = probe_deployment_capabilities(provider)

    assert result["overall_status"] == "FAIL"
    assert result["probes"]["chat"]["http_status"] == 200
    assert result["probes"]["chat"]["error_category"] == "BAD_REQUEST"
    assert "finish_reason=length" in result["probes"]["chat"]["safe_message"]
    assert "reasoning_tokens=16" in result["probes"]["chat"]["safe_message"]


def test_utf8_probe():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        return _baseline_handler(payload, json_schema="unsupported")

    provider = _provider(handler)
    result = probe_deployment_capabilities(provider)
    assert result["probes"]["utf8"]["status"] == "SUPPORTED"


def test_secret_not_in_probe_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="invalid api_key: test-credential bearer")

    provider = _provider(handler)
    result = probe_deployment_capabilities(provider)
    blob = json.dumps(result)
    assert "test-credential" not in blob


def test_deployment_capability_overrides_provider_for_routing():
    spec = ProviderSpec(
        provider_type="DEEPSEEK",
        name="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        model="m",
        is_local=False,
        api_key_env="DEEPSEEK_API_KEY",
        configured=True,
        capabilities={"supports_json_object": False, "supports_json_schema": False},
    )
    with pytest.raises(RoutingError) as exc:
        _check_capability("ANALYSIS", spec)
    assert exc.value.code == "STRUCTURED_OUTPUT_UNAVAILABLE"


def test_probe_updates_route_eligibility():
    caps = apply_probe_capabilities(
        {"supports_json_object": False, "supports_json_schema": False},
        {
            "json_object": {"status": "SUPPORTED"},
            "json_schema": {"status": "UNSUPPORTED"},
            "streaming": {"status": "UNKNOWN"},
        },
    )
    spec = ProviderSpec(
        provider_type="X",
        name="X",
        base_url="http://127.0.0.1/v1",
        model="m",
        is_local=True,
        api_key_env=None,
        configured=True,
        capabilities=caps,
    )
    _check_capability("ANALYSIS", spec)
