"""MiniMax image generation adapter."""

from __future__ import annotations

import base64
import binascii
import time
from dataclasses import dataclass
from typing import Any

import httpx

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.services.image.minimax_contract import MAX_PROMPT_CHARS, parse_image_generation_body, validate_effective_prompt
from app.services.image.minimax_validate import MinimaxImageValidationError, validate_cover_image_bytes
from app.services.llm.credential_resolver import resolve_api_key
from app.services.secrets.vault import CredentialVaultError, read_vault_secret


class MinimaxImageError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class MinimaxImageResult:
    ok: bool
    image_bytes: bytes | None
    latency_ms: int
    model: str
    code: str | None = None
    message: str | None = None
    raw: dict[str, Any] | None = None
    http_status: int | None = None
    business_status: int | None = None
    success_count: int | None = None


def _fake_png_bytes() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )


def _resolved_minimax_key(settings: Settings, session: Session | None = None) -> str:
    if session is not None:
        # The UI-managed M Plan key must never silently fall back to a legacy
        # pay-as-you-go environment or .env key.
        try:
            return (read_vault_secret(session, "MINIMAX_IMAGE") or "").strip()
        except CredentialVaultError as exc:
            raise MinimaxImageError(exc.code, exc.message) from exc
    return resolve_api_key("MINIMAX_IMAGE", "MINIMAX_API_KEY", settings, session).value


def query_token_plan_remains(api_key: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    """Read MiniMax Token Plan status without exposing credentials or raw body."""
    owns = client is None
    http = client or httpx.Client(timeout=httpx.Timeout(15.0), follow_redirects=False)
    try:
        response = http.get(
            "https://www.minimax.cn/v1/token_plan/remains",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
    except httpx.TimeoutException:
        return {"status": "UNAVAILABLE", "code": "TOKEN_PLAN_TIMEOUT"}
    except httpx.RequestError as exc:
        return {"status": "UNAVAILABLE", "code": "TOKEN_PLAN_NETWORK_ERROR", "detail": type(exc).__name__}
    finally:
        if owns:
            http.close()

    if response.status_code in (404, 405, 501):
        return {"status": "UNSUPPORTED", "code": "TOKEN_PLAN_ENDPOINT_UNSUPPORTED", "http_status": response.status_code}
    if response.status_code in (401, 403):
        return {"status": "AUTH_FAILED", "code": "TOKEN_PLAN_AUTH_FAILED", "http_status": response.status_code}
    if response.status_code >= 400:
        return {"status": "UNAVAILABLE", "code": "TOKEN_PLAN_HTTP_ERROR", "http_status": response.status_code}
    try:
        body = response.json()
    except ValueError:
        return {"status": "UNAVAILABLE", "code": "TOKEN_PLAN_INVALID_RESPONSE", "http_status": response.status_code}
    rows = body.get("model_remains") if isinstance(body, dict) else None
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return {"status": "UNAVAILABLE", "code": "TOKEN_PLAN_FIELDS_MISSING", "http_status": response.status_code}
    row = rows[0]
    interval = row.get("current_interval_remaining_percent")
    weekly = row.get("current_weekly_remaining_percent")
    interval_status = row.get("current_interval_status")
    weekly_status = row.get("current_weekly_status")
    if not all(isinstance(value, (int, float)) for value in (interval, weekly)):
        return {"status": "UNAVAILABLE", "code": "TOKEN_PLAN_FIELDS_MISSING", "http_status": response.status_code}
    if interval_status not in (1, "1") or weekly_status not in (1, "1"):
        return {"status": "INACTIVE", "code": "TOKEN_PLAN_INACTIVE", "http_status": response.status_code}
    available = float(interval) > 0 and float(weekly) > 0
    return {
        "status": "AVAILABLE" if available else "EXHAUSTED",
        "code": None if available else "TOKEN_PLAN_QUOTA_EXHAUSTED",
        "http_status": response.status_code,
        "current_interval_usage_count": row.get("current_interval_usage_count"),
        "current_interval_remaining_percent": interval,
        "weekly_usage_count": row.get("current_weekly_usage_count"),
        "weekly_remaining_percent": weekly,
        "remains_time_seconds": row.get("remains_time"),
        "weekly_remains_time_seconds": row.get("weekly_remains_time"),
        "quota_unit": "shared_token_plan_percentage",
    }


def probe_token_plan(settings: Settings | None = None, session: Session | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    try:
        api_key = _resolved_minimax_key(settings, session)
    except MinimaxImageError as exc:
        return {"status": "UNAVAILABLE", "code": exc.code, "message": exc.message}
    if not api_key:
        return {"status": "NOT_CONFIGURED", "code": "VAULT_CREDENTIAL_REQUIRED"}
    return query_token_plan_remains(api_key)


def generate_image(
    prompt: str,
    *,
    model: str | None = None,
    aspect_ratio: str = "16:9",
    settings: Settings | None = None,
    client: httpx.Client | None = None,
    force_fake: bool | None = None,
    session: Session | None = None,
) -> MinimaxImageResult:
    settings = settings or get_settings()
    model = model or settings.minimax_image_model
    use_fake = settings.minimax_enable_fake if force_fake is None else force_fake
    try:
        safe_prompt = validate_effective_prompt(prompt, stage="minimax_adapter")
    except ValueError as exc:
        message = str(exc)
        if message.startswith("COVER_PROMPT_TOO_LONG:"):
            parts = message.split(":")
            actual = parts[1] if len(parts) > 1 else "?"
            return MinimaxImageResult(
                ok=False,
                image_bytes=None,
                latency_ms=0,
                model=model,
                code="COVER_PROMPT_TOO_LONG",
                message=f"提示词过长（{actual}/{MAX_PROMPT_CHARS} 字符，阶段 minimax_adapter）。",
            )
        return MinimaxImageResult(
            ok=False,
            image_bytes=None,
            latency_ms=0,
            model=model,
            code="PROMPT_REQUIRED",
            message="提示词不能为空。",
        )
    if use_fake:
        return MinimaxImageResult(ok=True, image_bytes=_fake_png_bytes(), latency_ms=5, model=model, code="FAKE_OK")

    api_key = _resolved_minimax_key(settings, session)
    if not api_key:
        raise MinimaxImageError("VAULT_CREDENTIAL_REQUIRED", "订阅模式要求使用设置页面安全存储中的 MiniMax Key，未回退到环境变量或旧 Key。")

    if session is not None:
        plan = query_token_plan_remains(api_key, client=client)
        if plan["status"] != "AVAILABLE":
            raise MinimaxImageError(plan.get("code") or "TOKEN_PLAN_UNAVAILABLE", f"MiniMax 订阅额度状态不可用（{plan['status']}），已阻止图像请求。")

    url = f"{settings.minimax_base_url.rstrip('/')}/v1/image_generation"
    payload = {
        "model": model,
        "prompt": safe_prompt,
        "aspect_ratio": aspect_ratio,
        "response_format": "base64",
        "n": 1,
    }
    owns = client is None
    http = client or httpx.Client(timeout=httpx.Timeout(90.0))
    started = time.perf_counter()
    try:
        response = http.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        latency = int((time.perf_counter() - started) * 1000)
        if response.status_code == 429:
            return MinimaxImageResult(
                ok=False,
                image_bytes=None,
                latency_ms=latency,
                model=model,
                code="RATE_LIMIT",
                message="MiniMax 限流。",
                http_status=429,
            )
        body: dict[str, Any] = {}
        try:
            parsed_json = response.json()
            if isinstance(parsed_json, dict):
                body = parsed_json
        except ValueError:
            body = {}

        if response.status_code >= 400:
            parsed = parse_image_generation_body(body) if body else None
            if parsed and not parsed.ok:
                return MinimaxImageResult(
                    ok=False,
                    image_bytes=None,
                    latency_ms=latency,
                    model=model,
                    code=parsed.internal_code,
                    message=parsed.user_message,
                    raw=body or None,
                    http_status=response.status_code,
                    business_status=parsed.business_status,
                    success_count=parsed.success_count,
                )
            return MinimaxImageResult(
                ok=False,
                image_bytes=None,
                latency_ms=latency,
                model=model,
                code="HTTP_ERROR",
                message=f"HTTP {response.status_code}",
                raw=body or None,
                http_status=response.status_code,
            )

        parsed = parse_image_generation_body(body)
        if not parsed.ok:
            return MinimaxImageResult(
                ok=False,
                image_bytes=None,
                latency_ms=latency,
                model=model,
                code=parsed.internal_code,
                message=parsed.user_message,
                raw=body,
                http_status=response.status_code,
                business_status=parsed.business_status,
                success_count=parsed.success_count,
            )

        try:
            raw = base64.b64decode(parsed.images[0], validate=True)
        except (binascii.Error, ValueError) as exc:
            return MinimaxImageResult(
                ok=False,
                image_bytes=None,
                latency_ms=latency,
                model=model,
                code="INVALID_BASE64",
                message="Base64 图片数据无效。",
                raw=body,
                http_status=response.status_code,
                business_status=parsed.business_status,
                success_count=parsed.success_count,
            )
        try:
            validate_cover_image_bytes(raw, max_bytes=settings.cover_max_bytes)
        except MinimaxImageValidationError as exc:
            return MinimaxImageResult(
                ok=False,
                image_bytes=None,
                latency_ms=latency,
                model=model,
                code=exc.code,
                message=exc.message,
                raw=body,
                http_status=response.status_code,
                business_status=parsed.business_status,
                success_count=parsed.success_count,
            )
        return MinimaxImageResult(
            ok=True,
            image_bytes=raw,
            latency_ms=latency,
            model=model,
            raw=body,
            http_status=response.status_code,
            business_status=parsed.business_status,
            success_count=parsed.success_count,
        )
    except httpx.TimeoutException as exc:
        raise MinimaxImageError("TIMEOUT", "MiniMax 图像生成超时。") from exc
    finally:
        if owns:
            http.close()


def probe_image_config(settings: Settings | None = None, session: Session | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    if settings.minimax_enable_fake:
        return {
            "ok": True,
            "overall_status": "PASS",
            "mode": "fake",
            "provider_type": "MINIMAX_IMAGE",
            "model": settings.minimax_image_model,
            "message": "Fake MiniMax 图像适配器已启用。",
        }
    api_key = _resolved_minimax_key(settings, session)
    if not api_key:
        return {
            "ok": False,
            "overall_status": "NOT_CONFIGURED",
            "code": "NOT_CONFIGURED",
            "provider_type": "MINIMAX_IMAGE",
            "model": settings.minimax_image_model,
            "message": "MiniMax API Key 未配置。",
        }
    return {
        "ok": True,
        "overall_status": "CONFIGURED",
        "mode": "config_check",
        "provider_type": "MINIMAX_IMAGE",
        "model": settings.minimax_image_model,
        "endpoint": f"{settings.minimax_base_url.rstrip('/')}/v1/image_generation",
        "message": "API Key 已配置。真实生图测试可能产生费用。",
    }


def probe_image_sample(
    prompt: str,
    *,
    model: str | None = None,
    settings: Settings | None = None,
    session: Session | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    result = generate_image(prompt, model=model, settings=settings, session=session)
    return {
        "ok": result.ok,
        "overall_status": "PASS" if result.ok else "FAIL",
        "provider_type": "MINIMAX_IMAGE",
        "model": result.model,
        "latency_ms": result.latency_ms,
        "code": result.code,
        "message": result.message,
        "image_valid": bool(result.image_bytes),
        "mode": "sample_generation",
        "business_status": result.business_status,
    }
