import json

import httpx

from app.core.config import Settings
from app.services.llm.provider import FakeLLMProvider, OpenAICompatibleProvider
from app.services.llm.types import LLMRequest
from app.services.retrieval.ask import AskService
from app.services.retrieval.coverage import COVERAGE, FOCUSED, PLAN_SCHEMA, parse_plan


def test_parse_plan_accepts_lowercase_mode():
    payload = json.dumps(
        {
            "mode": "focused",
            "needs_cross_source": False,
            "requested_scope": "CURRENT_FILTER_SCOPE",
            "reason": "test",
        }
    )
    parsed = parse_plan(payload)
    assert parsed is not None
    assert parsed["mode"] == FOCUSED


def test_parse_plan_rejects_wrong_scope():
    payload = json.dumps(
        {
            "mode": "FOCUSED",
            "needs_cross_source": False,
            "requested_scope": "ALL",
            "reason": "test",
        }
    )
    assert parse_plan(payload) is None


def test_json_object_transport_includes_schema_guidance():
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "mode": "FOCUSED",
                                    "needs_cross_source": False,
                                    "requested_scope": "CURRENT_FILTER_SCOPE",
                                    "reason": "ok",
                                }
                            )
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                "model": "mock",
            },
        )

    provider = OpenAICompatibleProvider(
        provider_type="DEEPSEEK",
        base_url="https://api.example.com/v1",
        model="mock",
        api_key="test-credential",
        is_local=False,
        timeout=2,
        max_retries=0,
        supports_json_schema=False,
        supports_json_object=True,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    response = provider.complete(
        LLMRequest(
            "system",
            "Question:\nWhat is OpenKB?",
            PLAN_SCHEMA,
            0,
            200,
            {"purpose": "ask_plan", "schema_name": "ask_plan"},
        )
    )
    assert bodies
    user = bodies[0]["messages"][1]["content"]
    assert "Respond with JSON only" in user
    assert '"mode"' in user
    assert parse_plan(response.text) is not None


def _settings() -> Settings:
    return Settings(llm_enable_fake=True, llm_default_provider="FAKE")


def test_ask_plan_fake_provider_structured_success(db_session):
    ask = AskService(db_session, _settings(), inline=True)
    plan = ask._plan(FakeLLMProvider(), "分别概括每条资料")
    assert plan["fallback"] is False
    assert plan["mode"] == COVERAGE


def test_ask_plan_malformed_json_uses_fallback(db_session):
    original = FakeLLMProvider.complete

    def broken(self, request):
        from app.services.llm.types import LLMResponse

        self.calls.append(request)
        return LLMResponse("not json", None, "fake", "FAKE", 1, 1, 2, 1, "stop", {})

    FakeLLMProvider.complete = broken
    try:
        plan = AskService(db_session, _settings(), inline=True)._plan(FakeLLMProvider(), "OpenKB?")
    finally:
        FakeLLMProvider.complete = original
    assert plan["fallback"] is True
    assert plan["structured_parse_failed"] is True

