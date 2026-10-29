"""Per-deployment capability probes over OpenAI-compatible chat completions."""

from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from app.services.llm.provider import _rejects_json_object, _safe_message, apply_zai_request_parameters

PROBE_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}

TRANSIENT_HTTP = {429, 500, 502, 503, 504}


def _probe_result(
    status: str,
    *,
    latency_ms: int | None = None,
    error_category: str | None = None,
    safe_message: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "latency_ms": latency_ms,
        "error_category": error_category,
        "safe_message": safe_message,
    }


def _redact(text: str) -> str:
    clean = re.sub(r"(?i)(bearer\s+)[^\s\"']+", r"\1[REDACTED]", text or "")
    clean = re.sub(r"(?i)(api[_ -]?key\s*[:=]\s*)[^\s,\"']+", r"\1[REDACTED]", clean)
    clean = re.sub(r"(?i)\bsk-[A-Za-z0-9_-]+\b", "[REDACTED]", clean)
    return clean[:300]


def _provider_error_details(response: httpx.Response, provider) -> tuple[str | None, str | None]:
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError):
        return None, _redact(response.text) or None
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        error = body if isinstance(body, dict) else {}
    code = error.get("code")
    message = error.get("message") or body.get("message") if isinstance(body, dict) else None
    if message:
        key = getattr(provider, "api_key", "") or ""
        if key:
            message = str(message).replace(key, "[REDACTED]")
        message = _redact(str(message))
    return (str(code)[:100] if code is not None else None, message or None)


def _headers(provider) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = getattr(provider, "api_key", "") or ""
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _chat_url(provider) -> str:
    return f"{provider.base_url.rstrip('/')}/chat/completions"


def _parse_message(response: httpx.Response) -> tuple[str | None, str | None]:
    try:
        body = response.json()
    except json.JSONDecodeError:
        return None, "响应不是 JSON"
    choice = (body.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    model = str(body.get("model") or "")
    text = message.get("content") or choice.get("text") or ""
    if isinstance(text, list):
        text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
    return (str(text), model or None)


def _classify_http(status: int, text: str, *, capability_probe: bool) -> tuple[str, str, str]:
    """Return probe status, error_category, safe_message."""
    body = _redact(text)
    if status == 401:
        return "UNSUPPORTED", "AUTH_ERROR", f"HTTP {status}"
    if status == 403:
        return "UNSUPPORTED", "PERMISSION_ERROR", f"HTTP {status}"
    if status == 429:
        return "TRANSIENT_FAILURE", "RATE_LIMITED", f"HTTP {status}"
    if status in TRANSIENT_HTTP:
        return "TRANSIENT_FAILURE", "PROVIDER_OVERLOADED", f"HTTP {status}"
    if capability_probe and status in {400, 422} and _rejects_json_object(response_like(text)):
        return "UNSUPPORTED", "UNSUPPORTED_CAPABILITY", f"HTTP {status}"
    if capability_probe and status in {400, 422}:
        lower = body.lower()
        if any(token in lower for token in ("response_format", "json_schema", "json_object", "structured")):
            return "UNSUPPORTED", "UNSUPPORTED_CAPABILITY", f"HTTP {status}"
    if status == 404:
        return "UNSUPPORTED", "MODEL_NOT_FOUND", f"HTTP {status}"
    if status >= 400:
        return "UNKNOWN", "UNKNOWN_PROVIDER_ERROR", f"HTTP {status}"
    return "UNKNOWN", "UNKNOWN_PROVIDER_ERROR", f"HTTP {status}"


def response_like(text: str):
    class _R:
        def __init__(self, value: str) -> None:
            self.text = value

    return _R(text)


def _post_json(provider, client: httpx.Client, payload: dict, *, capability_probe: bool) -> tuple[httpx.Response | None, int, str | None]:
    payload = apply_zai_request_parameters(getattr(provider, "provider_type", ""), getattr(provider, "model", ""), dict(payload))
    started = time.perf_counter()
    try:
        response = client.post(_chat_url(provider), json=payload, headers=_headers(provider))
    except httpx.TimeoutException:
        latency = int((time.perf_counter() - started) * 1000)
        return None, latency, "TIMEOUT"
    except httpx.HTTPError as exc:
        latency = int((time.perf_counter() - started) * 1000)
        return None, latency, _safe_message(exc)
    latency = int((time.perf_counter() - started) * 1000)
    if response.status_code >= 400:
        status, category, message = _classify_http(response.status_code, response.text, capability_probe=capability_probe)
        return response, latency, f"{category}:{message}"
    return response, latency, None


def _validate_probe_schema(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    if set(data.keys()) - {"ok"}:
        return False
    return data.get("ok") is True


def _probe_chat(provider, client: httpx.Client) -> dict[str, Any]:
    payload = {
        "model": provider.model,
        # GLM reasoning tokens share the generation budget; 16 tokens often leaves no answer text.
        "max_tokens": 512 if getattr(provider, "provider_type", "") == "ZAI" else 16,
        "messages": [
            {"role": "system", "content": "Reply with exactly: OK"},
            {"role": "user", "content": "ping"},
        ],
    }
    response, latency, err = _post_json(provider, client, payload, capability_probe=False)
    if err and response is None:
        category = "TIMEOUT" if err == "TIMEOUT" else "UNKNOWN_PROVIDER_ERROR"
        status = "TRANSIENT_FAILURE" if category == "TIMEOUT" else "UNKNOWN"
        return _probe_result(status, latency_ms=latency, error_category=category, safe_message=err)
    if response is None or response.status_code >= 400:
        status, category, message = _classify_http(response.status_code if response else 500, response.text if response else "", capability_probe=False)
        if category == "AUTH_ERROR":
            status = "UNSUPPORTED"
        code, provider_message = _provider_error_details(response, provider) if response is not None else (None, None)
        return {**_probe_result(status, latency_ms=latency, error_category=category, safe_message=provider_message or message), "http_status": response.status_code if response else None, "provider_error_code": code, "provider_error_message": provider_message}
    content, _ = _parse_message(response)
    if not (content or "").strip():
        body = response.json()
        choice = (body.get("choices") or [{}])[0]
        usage = body.get("usage") or {}
        details = usage.get("completion_tokens_details") or {}
        finish_reason = choice.get("finish_reason")
        msg = f"empty chat content (finish_reason={finish_reason or 'unknown'}, completion_tokens={usage.get('completion_tokens', 'unknown')}, reasoning_tokens={details.get('reasoning_tokens', 'unknown')})"
        return {**_probe_result("UNSUPPORTED", latency_ms=latency, error_category="BAD_REQUEST", safe_message=msg), "http_status": response.status_code, "finish_reason": finish_reason, "usage": usage}
    body = response.json()
    choice = (body.get("choices") or [{}])[0]
    return {**_probe_result("SUPPORTED", latency_ms=latency), "http_status": response.status_code, "finish_reason": choice.get("finish_reason"), "usage": body.get("usage")}


def _probe_utf8(provider, client: httpx.Client) -> dict[str, Any]:
    payload = {
        "model": provider.model,
        "max_tokens": 512 if getattr(provider, "provider_type", "") == "ZAI" else 64,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": 'Return exactly one JSON object: {"text":"你好，世界"}'},
            {"role": "user", "content": "utf8"},
        ],
    }
    response, latency, err = _post_json(provider, client, payload, capability_probe=False)
    if err and response is None:
        category = "TIMEOUT" if err == "TIMEOUT" else "UNKNOWN_PROVIDER_ERROR"
        status = "TRANSIENT_FAILURE" if category == "TIMEOUT" else "UNKNOWN"
        return _probe_result(status, latency_ms=latency, error_category=category, safe_message=err)
    if response is None or response.status_code >= 400:
        status, category, message = _classify_http(response.status_code if response else 500, response.text if response else "", capability_probe=False)
        return _probe_result(status, latency_ms=latency, error_category=category, safe_message=message)
    content, _ = _parse_message(response)
    if not content:
        return _probe_result("UNSUPPORTED", latency_ms=latency, error_category="BAD_REQUEST", safe_message="utf8 check failed")
    try:
        import json

        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("no json")
        parsed = json.loads(content[start : end + 1])
        text = str(parsed.get("text") or "")
    except Exception:
        return _probe_result("UNSUPPORTED", latency_ms=latency, error_category="BAD_REQUEST", safe_message="utf8 json parse failed")
    if "你好" not in text or "世界" not in text:
        return _probe_result("UNSUPPORTED", latency_ms=latency, error_category="BAD_REQUEST", safe_message="utf8 roundtrip failed")
    return _probe_result("SUPPORTED", latency_ms=latency)


def _probe_json_object(provider, client: httpx.Client) -> dict[str, Any]:
    payload = {
        "model": provider.model,
        "max_tokens": 512 if getattr(provider, "provider_type", "") == "ZAI" else 64,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "Return exactly one JSON object with {\"ok\": true} and nothing else."},
            {"role": "user", "content": "json"},
        ],
    }
    response, latency, err = _post_json(provider, client, payload, capability_probe=True)
    if err and response is None:
        category = "TIMEOUT" if err == "TIMEOUT" else "UNKNOWN_PROVIDER_ERROR"
        status = "TRANSIENT_FAILURE" if category == "TIMEOUT" else "UNKNOWN"
        return _probe_result(status, latency_ms=latency, error_category=category, safe_message=err)
    if response is None or response.status_code >= 400:
        status, category, message = _classify_http(response.status_code if response else 500, response.text if response else "", capability_probe=True)
        if category in {"RATE_LIMITED", "PROVIDER_OVERLOADED", "TIMEOUT"}:
            status = "TRANSIENT_FAILURE"
        elif category != "UNSUPPORTED_CAPABILITY":
            status = "UNKNOWN"
        return _probe_result(status, latency_ms=latency, error_category=category, safe_message=message.split(":", 1)[-1])
    content, _ = _parse_message(response)
    try:
        parsed = json.loads(content or "")
    except json.JSONDecodeError:
        return _probe_result("UNSUPPORTED", latency_ms=latency, error_category="BAD_REQUEST", safe_message="response not json object")
    if not isinstance(parsed, dict) or parsed.get("ok") is not True:
        return _probe_result("UNSUPPORTED", latency_ms=latency, error_category="BAD_REQUEST", safe_message="json object missing ok")
    return _probe_result("SUPPORTED", latency_ms=latency)


def _probe_json_schema(provider, client: httpx.Client) -> dict[str, Any]:
    payload = {
        "model": provider.model,
        "max_tokens": 512 if getattr(provider, "provider_type", "") == "ZAI" else 64,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "probe_ok", "strict": True, "schema": PROBE_SCHEMA},
        },
        "messages": [
            {"role": "system", "content": "Return JSON matching the schema with ok=true."},
            {"role": "user", "content": "schema"},
        ],
    }
    response, latency, err = _post_json(provider, client, payload, capability_probe=True)
    if err and response is None:
        category = "TIMEOUT" if err == "TIMEOUT" else "UNKNOWN_PROVIDER_ERROR"
        status = "TRANSIENT_FAILURE" if category == "TIMEOUT" else "UNKNOWN"
        return _probe_result(status, latency_ms=latency, error_category=category, safe_message=err)
    if response is None or response.status_code >= 400:
        status, category, message = _classify_http(response.status_code if response else 500, response.text if response else "", capability_probe=True)
        if category in {"RATE_LIMITED", "PROVIDER_OVERLOADED"}:
            status = "TRANSIENT_FAILURE"
        elif category != "UNSUPPORTED_CAPABILITY":
            status = "UNKNOWN"
        return _probe_result(status, latency_ms=latency, error_category=category, safe_message=message.split(":", 1)[-1])
    content, _ = _parse_message(response)
    try:
        parsed = json.loads(content or "")
    except json.JSONDecodeError:
        return _probe_result("UNSUPPORTED", latency_ms=latency, error_category="BAD_REQUEST", safe_message="response not json")
    if not _validate_probe_schema(parsed):
        return _probe_result("UNSUPPORTED", latency_ms=latency, error_category="BAD_REQUEST", safe_message="schema validation failed")
    return _probe_result("SUPPORTED", latency_ms=latency)


def _probe_streaming(provider, client: httpx.Client) -> dict[str, Any]:
    payload = {
        "model": provider.model,
        "max_tokens": 512 if getattr(provider, "provider_type", "") == "ZAI" else 64,
        "stream": True,
        "stream_options": {"include_usage": True},
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "Respond with JSON only."},
            {"role": "user", "content": "Return {\"ok\": true} as JSON."},
        ],
    }
    payload = apply_zai_request_parameters(getattr(provider, "provider_type", ""), getattr(provider, "model", ""), payload)
    if getattr(provider, "provider_type", "") == "ZAI":
        payload.pop("stream_options", None)
    started = time.perf_counter()
    content_deltas = 0
    assembled = ""
    try:
        with client.stream("POST", _chat_url(provider), json=payload, headers=_headers(provider)) as response:
            if response.status_code >= 400:
                latency = int((time.perf_counter() - started) * 1000)
                status, category, message = _classify_http(response.status_code, response.read().decode("utf-8", errors="replace"), capability_probe=True)
                if category in {"RATE_LIMITED", "PROVIDER_OVERLOADED"}:
                    status = "TRANSIENT_FAILURE"
                elif category == "UNSUPPORTED_CAPABILITY" or "stream" in message.lower():
                    status = "UNSUPPORTED"
                else:
                    status = "UNKNOWN"
                return _probe_result(status, latency_ms=latency, error_category=category, safe_message=message)
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
                delta = ((body.get("choices") or [{}])[0].get("delta") or {}).get("content")
                if isinstance(delta, str) and delta:
                    content_deltas += 1
                    assembled += delta
    except httpx.TimeoutException:
        latency = int((time.perf_counter() - started) * 1000)
        return _probe_result("TRANSIENT_FAILURE", latency_ms=latency, error_category="TIMEOUT", safe_message="timeout")
    except httpx.HTTPError as exc:
        latency = int((time.perf_counter() - started) * 1000)
        return _probe_result("UNKNOWN", latency_ms=latency, error_category="UNKNOWN_PROVIDER_ERROR", safe_message=_safe_message(exc))
    latency = int((time.perf_counter() - started) * 1000)
    if content_deltas < 2 or not assembled.strip():
        return _probe_result(
            "UNSUPPORTED",
            latency_ms=latency,
            error_category="BAD_REQUEST",
            safe_message=f"insufficient stream content deltas ({content_deltas})",
        )
    return _probe_result("SUPPORTED", latency_ms=latency)


def probe_deployment_capabilities(provider, *, client: httpx.Client | None = None) -> dict[str, Any]:
    timeout = float(getattr(provider, "timeout", 30) or 30)
    injected = getattr(provider, "client", None)
    owns = False
    if client is None and injected is not None:
        client = injected
    elif client is None:
        client = httpx.Client(timeout=timeout)
        owns = True
    started = time.perf_counter()
    probes: dict[str, Any] = {}
    chat = _probe_chat(provider, client)
    probes["chat"] = chat
    if chat["status"] != "SUPPORTED":
        total = int((time.perf_counter() - started) * 1000)
        return {
            "overall_status": "FAIL",
            "ok": False,
            "code": chat.get("error_category") or "CHAT_FAILED",
            "model": getattr(provider, "model", None),
            "resolved_model": getattr(provider, "model", None),
            "latency_ms": chat.get("latency_ms"),
            "total_latency_ms": total,
            "provider_type": getattr(provider, "provider_type", None),
            "is_local": bool(getattr(provider, "is_local", False)),
            "probes": probes,
        }
    probes["utf8"] = _probe_utf8(provider, client)
    probes["json_object"] = _probe_json_object(provider, client)
    probes["json_schema"] = _probe_json_schema(provider, client)
    probes["streaming"] = _probe_streaming(provider, client)
    total = int((time.perf_counter() - started) * 1000)
    resolved = getattr(provider, "model", None)
    if owns:
        client.close()
    return {
        "overall_status": "PASS",
        "ok": True,
        "code": None,
        "model": resolved,
        "resolved_model": resolved,
        "latency_ms": chat.get("latency_ms"),
        "total_latency_ms": total,
        "provider_type": getattr(provider, "provider_type", None),
        "is_local": bool(getattr(provider, "is_local", False)),
        "probes": probes,
        "chinese_ok": probes["utf8"]["status"] == "SUPPORTED",
        "structured_strategy": "JSON_SCHEMA" if probes["json_schema"]["status"] == "SUPPORTED" else ("JSON_OBJECT" if probes["json_object"]["status"] == "SUPPORTED" else None),
    }


def apply_probe_capabilities(existing: dict | None, probes: dict[str, Any]) -> dict[str, Any]:
    from datetime import datetime, timezone

    caps = dict(existing or {})
    mapping = {
        "json_object": "supports_json_object",
        "json_schema": "supports_json_schema",
        "streaming": "supports_streaming",
    }
    summary: dict[str, str] = {}
    for probe_key, cap_key in mapping.items():
        entry = probes.get(probe_key) or {}
        status = str(entry.get("status") or "UNKNOWN")
        summary[probe_key] = status
        if status == "SUPPORTED":
            caps[cap_key] = True
        elif status == "UNSUPPORTED":
            caps[cap_key] = False
    caps["last_probe_at"] = datetime.now(timezone.utc).isoformat()
    caps["last_probe_summary"] = summary
    for probe_key in mapping:
        entry = probes.get(probe_key) or {}
        if entry.get("status"):
            caps[f"verified_{probe_key}"] = entry.get("status")
    return caps


def workflow_eligibility(capabilities: dict | None) -> dict[str, bool]:
    caps = capabilities or {}
    if caps.get("supports_image_generation"):
        return {
            "ANALYSIS": False,
            "ASK_PLANNER": False,
            "BRIEF": False,
            "ASK_ANSWER": False,
            "COVER_IMAGE": True,
        }
    structured = bool(caps.get("supports_json_schema") or caps.get("supports_json_object"))
    return {
        "ANALYSIS": structured,
        "ASK_PLANNER": structured,
        "BRIEF": structured,
        "ASK_ANSWER": True,
        "COVER_IMAGE": False,
    }
