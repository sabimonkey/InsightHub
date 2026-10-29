import json

import httpx

from app.services.llm.provider import ZaiProvider
from app.services.llm.types import LLMError, LLMRequest
from app.services.extraction.zai_file_parser import ZAI_FILE_PARSER_URL, ZaiFileParser
from app.services.llm.capability_probe import _parse_message


def test_glm_53_flash_uses_only_supported_thinking_parameter():
    provider = ZaiProvider(
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-5.3-flash",
        api_key="test-key",
        timeout=1,
    )
    request = LLMRequest(
        system_prompt="system",
        user_content="Return JSON",
        response_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        max_output_tokens=600,
        metadata={"purpose": "analysis"},
    )

    payload, strategy, headers = provider._prepare_payload(request, stream=False)

    assert payload["model"] == "glm-5.3-flash"
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "low"
    assert "clear_thinking" not in payload["thinking"]
    assert payload["response_format"] == {"type": "json_object"}
    assert strategy == "JSON_OBJECT"
    assert headers["Authorization"] == "Bearer test-key"


def test_glm_reasoning_content_is_not_used_as_final_response():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "response-1",
                "model": "glm-5.3-flash",
                "choices": [{
                    "finish_reason": "stop",
                    "message": {
                        "reasoning_content": "private reasoning text",
                        "content": '{"ok":true}',
                    },
                }],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 8,
                    "total_tokens": 20,
                    "completion_tokens_details": {"reasoning_tokens": 5},
                },
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = ZaiProvider(
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-5.3-flash",
        api_key="test-key",
        client=client,
    )
    response = provider.complete(LLMRequest(system_prompt="system", user_content="Return JSON"))

    assert response.text == '{"ok":true}'
    assert response.finish_reason == "stop"
    assert response.input_tokens == 12
    assert response.output_tokens == 8
    assert response.total_tokens == 20
    assert response.raw_response_metadata["reasoning_content_present"] is True
    assert response.raw_response_metadata["reasoning_content_chars"] == len("private reasoning text")
    assert response.raw_response_metadata["usage_details"] == {"reasoning_tokens": 5}
    assert "private reasoning text" not in str(response.raw_response_metadata)
    assert seen["thinking"]["type"] == "enabled"
    assert response.raw_response_metadata["request_parameters"]["reasoning_effort"] == "low"
    assert response.raw_response_metadata["request_parameters"]["endpoint"] == "https://open.bigmodel.cn/api/paas/v4/chat/completions"


def test_capability_probe_does_not_treat_reasoning_as_model_answer():
    response = httpx.Response(200, json={"model": "glm-5.3-flash", "choices": [{"message": {"reasoning_content": "reason only"}}]})
    content, model = _parse_message(response)
    assert content == ""
    assert model == "glm-5.3-flash"


def test_glm_stream_enables_tool_stream_and_only_emits_final_content():
    events = [
        {"choices": [{"delta": {"reasoning_content": "reasoning"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "final"}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        body = "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = ZaiProvider(
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-5.3-flashx",
        api_key="test-key",
        client=client,
    )
    request = LLMRequest(system_prompt="system", user_content="question", metadata={"purpose": "ask_answer"})
    payload, _strategy, _headers = provider._prepare_payload(request, stream=True)
    deltas: list[str] = []
    result = provider.stream_completion(request, deltas.append)

    assert payload["thinking"] == {"type": "enabled"}
    assert "tool_stream" not in payload
    assert "stream_options" not in payload
    assert deltas == ["final"]
    assert result.text == "final"
    assert result.finish_reason == "stop"
    assert result.total_tokens == 3


def test_glm_endpoint_is_appended_once_and_probe_chat_uses_answer_budget():
    from app.services.llm.capability_probe import _probe_chat

    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"model": "glm-5.3-flash", "choices": [{"message": {"content": "OK"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = ZaiProvider(base_url="https://open.bigmodel.cn/api/paas/v4/", model="glm-5.3-flash", api_key="test-key", client=client)
    result = _probe_chat(provider, client)

    assert result["status"] == "SUPPORTED"
    assert seen["url"] == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    assert seen["payload"]["thinking"] == {"type": "enabled"}
    assert seen["payload"]["max_tokens"] >= 512
    assert "response_format" not in seen["payload"]
    assert seen["payload"]["reasoning_effort"] == "low"


def test_zai_probe_preserves_provider_error_code_and_redacts_key():
    from app.services.llm.capability_probe import _probe_chat

    key = "secret-provider-key"
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
        400,
        json={"error": {"code": "1210", "message": f"invalid parameter; {key}"}},
    )))
    provider = ZaiProvider(base_url="https://open.bigmodel.cn/api/paas/v4", model="glm-5.3-flashx", api_key=key, client=client)
    result = _probe_chat(provider, client)

    assert result["provider_error_code"] == "1210"
    assert key not in str(result)
    assert "invalid parameter" in result["provider_error_message"]


def test_production_adapter_preserves_redacted_provider_error_details():
    key = "provider-secret-token"
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
        400,
        json={"error": {"code": "1210", "message": f"invalid parameter {key}"}},
    )))
    provider = ZaiProvider(base_url="https://open.bigmodel.cn/api/paas/v4", model="glm-5.3-flash", api_key=key, client=client, max_retries=0)
    try:
        provider.complete(LLMRequest(system_prompt="system", user_content="hello"))
    except LLMError as exc:
        assert "1210" in exc.message
        assert "invalid parameter" in exc.message
        assert key not in exc.message
    else:
        raise AssertionError("expected provider error")


def test_zai_file_parser_uses_official_prime_sync_and_returns_source_text():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("Authorization")
        seen["body"] = request.read().decode("latin1")
        return httpx.Response(200, json={"status": "succeeded", "task_id": "task-1", "content": "# Report\n\nRevenue was 12."})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    parser = ZaiFileParser(api_key="test-key", client=client)
    payload = parser.parse(b"%PDF-1.4 fixture", "annual-report.pdf")

    assert seen["url"] == ZAI_FILE_PARSER_URL
    assert seen["authorization"] == "Bearer test-key"
    assert 'name="tool_type"' in seen["body"] and "prime-sync" in seen["body"]
    assert 'name="file_type"' in seen["body"] and "PDF" in seen["body"]
    assert payload.blocks[0].content == "# Report\n\nRevenue was 12."
    assert payload.metadata["task_id"] == "task-1"
    assert payload.metadata["billing_basis"] == "per_page"


def test_zai_file_parser_rejects_unsupported_file_type_without_network():
    parser = ZaiFileParser(api_key="test-key", client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500))))
    try:
        parser.parse(b"media", "clip.mp4")
    except ValueError as exc:
        assert str(exc) == "ZAI_FILE_TYPE_UNSUPPORTED"
    else:
        raise AssertionError("unsupported file type was accepted")
