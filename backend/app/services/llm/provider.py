import json
import re
import time
from collections.abc import Callable, Iterator
from urllib.parse import urlsplit

import httpx

from app.services.llm.types import LLMError, LLMRequest, LLMResponse

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def apply_zai_request_parameters(provider_type: str, model: str, payload: dict) -> dict:
    """Use bounded reasoning for InsightHub's grounded, structured workflows."""
    if provider_type == "ZAI" and model in {"glm-5.3-flash", "glm-5.3-flashx"}:
        payload["thinking"] = {"type": "enabled"}
        payload["reasoning_effort"] = "low"
    return payload


def _rejects_json_object(response: httpx.Response) -> bool:
    text = response.text.lower()
    return "response_format" in text and ("json_schema" in text or "json_object" in text)


def is_local_base_url(base_url: str) -> bool:
    host = (urlsplit(base_url).hostname or "").lower()
    return host in LOCAL_HOSTS


def _safe_message(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    lowered = text.lower()
    if any(word in lowered for word in ("api_key", "authorization", "bearer", "sk-")):
        return type(exc).__name__
    return text[:300]


def _provider_response_message(response: httpx.Response, api_key: str = "") -> str:
    try:
        body = response.json()
    except ValueError:
        body = None
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        error = body if isinstance(body, dict) else {}
    code = error.get("code")
    message = error.get("message") or (body.get("message") if isinstance(body, dict) else None)
    text = str(message or response.text or f"HTTP {response.status_code}")
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    text = re.sub(r"(?i)(bearer\s+)[^\s\"']+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)\bsk-[A-Za-z0-9_-]+\b", "[REDACTED]", text)
    prefix = f"{code}: " if code is not None else ""
    return f"{prefix}{text[:250]}"


def _json_schema_user_guidance(user_content: str, schema: dict | None) -> str:
    if not schema:
        return user_content
    if "Respond with JSON only" in user_content:
        return user_content
    compact = json.dumps(schema, ensure_ascii=False)
    extra = ""
    props = schema.get("properties") if isinstance(schema, dict) else None
    if isinstance(props, dict) and "reason" in props:
        extra = " Keep the reason field to one short sentence (max 120 characters)."
    return user_content + f"\n\nRespond with JSON only (no markdown fences).{extra} Schema:\n{compact}"


class OpenAICompatibleProvider:
    """Shared chat-completions transport. Named providers only change type and capabilities."""

    def __init__(
        self,
        *,
        provider_type: str,
        base_url: str,
        model: str,
        api_key: str = "",
        is_local: bool,
        timeout: float = 30,
        max_retries: int = 2,
        supports_json_schema: bool = False,
        supports_json_object: bool = True,
        client: httpx.Client | None = None,
    ) -> None:
        self.provider_type = provider_type
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.is_local = is_local and is_local_base_url(self.base_url)
        self.timeout = timeout
        self.max_retries = max_retries
        self.supports_json_schema = supports_json_schema
        self.supports_json_object = supports_json_object
        self.supports_vision = False
        self.supports_streaming = False
        self.client = client

    def _prepare_payload(self, request: LLMRequest, *, stream: bool) -> tuple[dict, str, dict]:
        if self.is_local and not is_local_base_url(self.base_url):
            raise LLMError("PRIVACY_PROVIDER_NOT_ALLOWED", "本地提供方的地址不是本机。")
        user_content = request.user_content
        payload = {
            "model": self.model,
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            "stream": stream,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": user_content},
            ],
        }
        strategy = "PROMPT_JSON"
        self._structured_strategy = strategy
        self._schema_notice = None
        if self.supports_json_schema and request.response_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": str((request.metadata or {}).get("schema_name") or "source_analysis"),
                    "strict": True,
                    "schema": request.response_schema,
                },
            }
            strategy = "JSON_SCHEMA"
            self._structured_strategy = strategy
        elif self.supports_json_object:
            payload["response_format"] = {"type": "json_object"}
            strategy = "JSON_OBJECT"
            self._structured_strategy = strategy
            if request.response_schema:
                user_content = _json_schema_user_guidance(user_content, request.response_schema)
                payload["messages"][1]["content"] = user_content
        purpose = str((request.metadata or {}).get("purpose") or "")
        apply_zai_request_parameters(self.provider_type, self.model, payload)
        if self.provider_type in {"DEEPSEEK", "SILICONFLOW"} and purpose in {"analysis", "repair", "brief", "ask_plan"}:
            payload["thinking"] = {"type": "disabled"}
        if stream and purpose == "ask_answer" and self.provider_type != "ZAI":
            payload["stream_options"] = {"include_usage": True}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return payload, strategy, headers

    def complete(self, request: LLMRequest) -> LLMResponse:
        payload, _strategy, headers = self._prepare_payload(request, stream=False)
        owns = self.client is None
        client = self.client or httpx.Client(timeout=self.timeout)
        started = time.perf_counter()
        try:
            response = self._post(client, payload, headers)
        finally:
            if owns:
                client.close()
        latency = int((time.perf_counter() - started) * 1000)
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise LLMError("PROVIDER_UNAVAILABLE", "模型响应不是 JSON。") from exc
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        text = message.get("content") or ""
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        usage_details: dict = {}
        completion_details = usage.get("completion_tokens_details")
        if isinstance(completion_details, dict) and completion_details.get("reasoning_tokens") is not None:
            usage_details["reasoning_tokens"] = completion_details.get("reasoning_tokens")
        return LLMResponse(
            text=text,
            structured_data=None,
            model=str(body.get("model") or self.model),
            provider=self.provider_type,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            latency_ms=latency,
            finish_reason=choice.get("finish_reason"),
            raw_response_metadata={
                "strategy": self._structured_strategy,
                "schema_notice": self._schema_notice,
                "http_status": response.status_code,
                "request_parameters": {
                    "endpoint": f"{self.base_url}/chat/completions",
                    **{key: payload[key] for key in ("model", "max_tokens", "thinking", "reasoning_effort", "stream") if key in payload},
                    "response_format": (payload.get("response_format") or {}).get("type"),
                },
                "id": body.get("id"),
                "reasoning_content_present": bool(message.get("reasoning_content")),
                "reasoning_content_chars": len(message.get("reasoning_content") or ""),
                "usage_details": usage_details or None,
            },
        )

    def iter_completion_deltas(self, request: LLMRequest) -> Iterator[str]:
        payload, _strategy, headers = self._prepare_payload(request, stream=True)
        url = f"{self.base_url}/chat/completions"
        owns = self.client is None
        client = self.client or httpx.Client(timeout=self.timeout)
        try:
            with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code >= 400:
                    response.read()
                    raise LLMError("PROVIDER_UNAVAILABLE", f"模型服务返回 HTTP {response.status_code}: {_provider_response_message(response, self.api_key)}")
                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        body = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    choice = (body.get("choices") or [{}])[0]
                    delta = (choice.get("delta") or {}).get("content")
                    if delta:
                        yield delta
        finally:
            if owns:
                client.close()

    def stream_completion(self, request: LLMRequest, on_delta: Callable[[str], None] | None = None) -> LLMResponse:
        started = time.perf_counter()
        first_token_ms: int | None = None
        parts: list[str] = []
        usage: dict = {}
        finish_reason = None
        model = self.model
        reasoning_content_present = False
        owns = self.client is None
        client = self.client or httpx.Client(timeout=self.timeout)
        payload, _strategy, headers = self._prepare_payload(request, stream=True)
        url = f"{self.base_url}/chat/completions"
        try:
            with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code >= 400:
                    response.read()
                    raise LLMError("PROVIDER_UNAVAILABLE", f"模型服务返回 HTTP {response.status_code}: {_provider_response_message(response, self.api_key)}")
                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        body = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(body.get("usage"), dict):
                        usage = body["usage"]
                    model = str(body.get("model") or model)
                    choice = (body.get("choices") or [{}])[0]
                    finish_reason = choice.get("finish_reason") or finish_reason
                    delta_message = choice.get("delta") or {}
                    reasoning_content_present = reasoning_content_present or bool(delta_message.get("reasoning_content"))
                    delta = delta_message.get("content")
                    if not delta:
                        continue
                    if first_token_ms is None:
                        first_token_ms = int((time.perf_counter() - started) * 1000)
                    parts.append(delta)
                    if on_delta:
                        on_delta(delta)
        finally:
            if owns:
                client.close()
        latency = int((time.perf_counter() - started) * 1000)
        stream_ms = (latency - (first_token_ms or 0)) if first_token_ms is not None else latency
        return LLMResponse(
            text="".join(parts),
            structured_data=None,
            model=model,
            provider=self.provider_type,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            latency_ms=latency,
            finish_reason=finish_reason,
            raw_response_metadata={
                "strategy": self._structured_strategy,
                "schema_notice": self._schema_notice,
                "http_status": response.status_code,
                "stream": True,
                "time_to_first_token_ms": first_token_ms,
                "answer_stream_duration_ms": stream_ms,
                "reasoning_content_present": reasoning_content_present,
                "usage_details": (
                    {"reasoning_tokens": usage.get("completion_tokens_details", {}).get("reasoning_tokens")}
                    if isinstance(usage.get("completion_tokens_details"), dict)
                    and usage["completion_tokens_details"].get("reasoning_tokens") is not None
                    else None
                ),
            },
        )

    def _post(self, client: httpx.Client, payload: dict, headers: dict) -> httpx.Response:
        url = f"{self.base_url}/chat/completions"
        attempt = 0
        dropped_schema = False
        dropped_format = False
        while True:
            try:
                response = client.post(url, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                if attempt >= self.max_retries:
                    raise LLMError("TIMEOUT", "模型请求超时。") from exc
                attempt += 1
                continue
            except httpx.HTTPError as exc:
                raise LLMError("PROVIDER_UNAVAILABLE", _safe_message(exc)) from exc
            format_type = (payload.get("response_format") or {}).get("type") if isinstance(payload.get("response_format"), dict) else None
            if response.status_code == 400 and format_type in {"json_schema", "json_object"} and _rejects_json_object(response):
                if format_type == "json_schema" and not dropped_schema and self.supports_json_object:
                    self._schema_notice = "NATIVE_JSON_SCHEMA_UNAVAILABLE"
                    payload["response_format"] = {"type": "json_object"}
                    self._structured_strategy = "JSON_OBJECT"
                    dropped_schema = True
                    continue
                if not dropped_format:
                    if format_type == "json_schema":
                        self._schema_notice = "NATIVE_JSON_SCHEMA_UNAVAILABLE"
                    payload.pop("response_format", None)
                    self._structured_strategy = "PROMPT_JSON_FALLBACK"
                    dropped_format = True
                    continue
            if response.status_code == 404:
                raise LLMError("MODEL_NOT_FOUND", f"模型或接口不存在。{_provider_response_message(response, self.api_key)}")
            if response.status_code == 401:
                raise LLMError("PROVIDER_UNAVAILABLE", f"模型服务拒绝了凭证。{_provider_response_message(response, self.api_key)}")
            if response.status_code in RETRYABLE_STATUS and attempt < self.max_retries:
                from app.services.llm.retry_policy import sleep_before_retry

                sleep_before_retry(
                    attempt=attempt,
                    status_code=response.status_code,
                    retry_after_header=response.headers.get("retry-after"),
                )
                attempt += 1
                continue
            if response.status_code == 429:
                raise LLMError("RATE_LIMITED", f"模型服务限流。{_provider_response_message(response, self.api_key)}")
            if response.status_code >= 400:
                code = "PROVIDER_UNAVAILABLE"
                if response.status_code in {502, 503, 504}:
                    code = "PROVIDER_OVERLOADED"
                raise LLMError(code, f"模型服务返回 HTTP {response.status_code}: {_provider_response_message(response, self.api_key)}")
            return response


class LocalOpenAICompatibleProvider(OpenAICompatibleProvider):
    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("supports_json_schema", True)
        super().__init__(provider_type="LOCAL_OPENAI_COMPATIBLE", is_local=True, **kwargs)


class GenericOpenAICompatibleProvider(OpenAICompatibleProvider):
    def __init__(self, **kwargs) -> None:
        super().__init__(provider_type="GENERIC_OPENAI_COMPATIBLE", is_local=False, **kwargs)


class DeepSeekProvider(OpenAICompatibleProvider):
    def __init__(self, **kwargs) -> None:
        super().__init__(provider_type="DEEPSEEK", is_local=False, **kwargs)


class SiliconFlowProvider(OpenAICompatibleProvider):
    def __init__(self, **kwargs) -> None:
        super().__init__(provider_type="SILICONFLOW", is_local=False, **kwargs)


class ZaiProvider(OpenAICompatibleProvider):
    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("supports_json_schema", False)
        kwargs.setdefault("supports_json_object", True)
        super().__init__(provider_type="ZAI", is_local=False, **kwargs)


class FakeLLMProvider:
    provider_type = "FAKE"
    is_local = True
    supports_json_schema = False
    supports_json_object = True
    supports_vision = False
    supports_streaming = True

    def __init__(self, model: str = "fake-model", script: list[str] | None = None, fail: str | None = None, finish_reasons: list[str] | None = None) -> None:
        self.model = model
        self.base_url = "http://127.0.0.1/fake"
        self.script = list(script or [])
        self.finish_reasons = list(finish_reasons or [])
        self.fail = fail
        self.calls: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if self.fail:
            raise LLMError(self.fail, "模型服务不可用。")
        purpose = str((request.metadata or {}).get("purpose") or "")
        if self.script:
            entry = self.script[0]
            text = entry(request) if callable(entry) else entry
            if len(self.script) > 1:
                self.script.pop(0)
        elif purpose == "ask_plan":
            text = _auto_plan(request.user_content)
        elif "Evidence packets:" in request.user_content:
            text = _auto_synthesis(request.user_content)
        elif "Question:" in request.user_content and "Evidence:" in request.user_content:
            text = _auto_ask(request.user_content)
        else:
            text = _auto_analysis(request.user_content)
        return LLMResponse(
            text=text,
            structured_data=None,
            model=self.model,
            provider=self.provider_type,
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
            latency_ms=5,
            finish_reason=self.finish_reasons.pop(0) if self.finish_reasons else "stop",
            raw_response_metadata={"strategy": "fake"},
        )

    def stream_completion(self, request: LLMRequest, on_delta: Callable[[str], None] | None = None) -> LLMResponse:
        started = time.perf_counter()
        response = self.complete(request)
        purpose = str((request.metadata or {}).get("purpose") or "")
        if purpose == "ask_answer" and on_delta and response.text:
            body = response.text
            step = max(1, len(body) // 4)
            throttle_ms = int((__import__("os").environ.get("ASK_FAKE_STREAM_CHUNK_MS") or "0"))
            for index in range(0, len(body), step):
                on_delta(body[index : index + step])
                if throttle_ms > 0:
                    time.sleep(throttle_ms / 1000)
        latency = int((time.perf_counter() - started) * 1000)
        return LLMResponse(
            text=response.text,
            structured_data=None,
            model=response.model,
            provider=self.provider_type,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            total_tokens=response.total_tokens,
            latency_ms=latency,
            finish_reason=response.finish_reason,
            raw_response_metadata={
                **(response.raw_response_metadata or {}),
                "stream": True,
                "time_to_first_token_ms": 1,
                "answer_stream_duration_ms": max(1, latency - 1),
            },
        )


def _auto_synthesis(user_content: str) -> str:
    import re

    items = re.findall(
        r"\[ITEM source_id=(\S+) claim_id=(\S+) chunk_id=(\S+) type=(\S+)\] (.+)",
        user_content,
    )
    points = []
    disagreements = []
    views = []
    for source_id, claim_id, chunk_id, claim_type, quote in items:
        statement = "FACT" if claim_type == "FACT" else "SOURCE_VIEW" if claim_type == "SOURCE_CLAIM" else "SYNTHESIS"
        point = {
            "text": quote.strip(),
            "statement_type": statement,
            "citations": [{"source_id": source_id, "claim_id": claim_id, "chunk_id": chunk_id, "quote": quote.strip()[:180]}],
        }
        points.append(point)
        if claim_type == "SOURCE_CLAIM":
            views.append(point)
    if len(views) >= 2:
        disagreements = views
    synthesis = []
    if len({item[0] for item in items}) >= 2:
        synthesis.append(
            {
                "text": "这些资料共同提示需要对照各方陈述，而不是合并成单一事实。",
                "statement_type": "SYNTHESIS",
                "citations": [point["citations"][0] for point in points[:2]],
            }
        )
    return json.dumps(
        {
            "title": "学习摘要",
            "executive_summary": "根据已验证资料整理。",
            "themes": [{"title": "主要主题", "summary": "来自 evidence packets。", "points": points}],
            "key_facts": [point for point in points if point["statement_type"] == "FACT"],
            "agreements": [],
            "disagreements": disagreements,
            "new_developments": [],
            "knowledge_to_remember": synthesis,
            "open_questions": [],
            "projects_or_tools": [],
        },
        ensure_ascii=False,
    )


def _auto_plan(user_content: str) -> str:
    import re

    from app.services.retrieval.coverage import COVERAGE, FOCUSED

    match = re.search(r"Question:\s*(.+)", user_content, flags=re.S)
    question = (match.group(1).strip() if match else user_content).strip()
    lowered = question.lower()
    coverage_markers = ("分别", "哪些", "每条", "every", "each", "all sources", "分别讲", "分别概括")
    mode = COVERAGE if any(marker in question or marker in lowered for marker in coverage_markers) else FOCUSED
    return json.dumps(
        {
            "mode": mode,
            "needs_cross_source": mode == COVERAGE,
            "requested_scope": "CURRENT_FILTER_SCOPE",
            "reason": "fake planner",
        },
        ensure_ascii=False,
    )


def _auto_ask(user_content: str) -> str:
    import re

    match = re.search(r"\[CHUNK: ([0-9a-fA-F-]{36})\][\s\S]*?\n([\s\S]*?)(?=\n\[CHUNK:|\Z)", user_content)
    chunk_id = match.group(1) if match else ""
    quote = ""
    if match:
        quote = next((line.strip() for line in match.group(2).splitlines() if line.strip() and not line.startswith("role=")), "")
    return json.dumps({"answer": f"根据资料可以确认：{quote}", "citations": [{"chunk_id": chunk_id, "quote": quote[:180]}]}, ensure_ascii=False)


def _auto_analysis(user_content: str) -> str:
    import re

    matches = re.findall(r"\[CHUNK: ([0-9a-fA-F-]{36})\][\s\S]*?Content:\n([\s\S]*?)(?=\n\[CHUNK:|\n</source_content>|\Z)", user_content)
    chunk_id = matches[0][0] if matches else "00000000-0000-0000-0000-000000000000"
    quote = "recorded fact sentence"
    if matches:
        line = next((item.strip() for item in matches[0][1].splitlines() if item.strip()), "")
        quote = line[:180] or quote
    elif "Intermediate analyses" in user_content:
        listed = re.findall(r"^- ([0-9a-fA-F-]{36})$", user_content, flags=re.MULTILINE)
        if listed:
            chunk_id = listed[0]
        try:
            start = user_content.find("[")
            if start >= 0:
                blob = json.loads(user_content[start : user_content.rfind("]") + 1])
                if isinstance(blob, list) and blob:
                    facts = blob[0].get("facts") or []
                    if facts and isinstance(facts[0], dict):
                        ev = (facts[0].get("evidence") or [{}])[0]
                        if isinstance(ev, dict) and ev.get("chunk_id"):
                            chunk_id = str(ev["chunk_id"])
                        if isinstance(ev, dict) and ev.get("quote"):
                            quote = str(ev["quote"])[:180]
        except (json.JSONDecodeError, TypeError, IndexError):
            pass
    payload = {
        "summary": "结构化摘要",
        "facts": [{"text": quote, "confidence": 0.9, "importance": 3, "evidence": [{"chunk_id": chunk_id, "quote": quote}]}],
        "source_claims": [],
        "inferences": [],
        "hypotheses": [],
        "unknowns": [],
        "questions": [],
        "category_candidates": [{"name": "知识", "confidence": 0.8, "reason": "资料内容"}],
        "topic_candidates": ["Agent"],
        "entities": [],
    }
    return json.dumps(payload, ensure_ascii=False)
