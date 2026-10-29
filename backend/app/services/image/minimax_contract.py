"""MiniMax image_generation OpenAPI response parsing (no secrets in logs)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

MAX_PROMPT_CHARS = 1500
DEFAULT_PROMPT_TARGET_CHARS = 1100

# base_resp.status_code -> (internal_code, user_message)
MINIMAX_STATUS_MAP: dict[int, tuple[str, str]] = {
    1002: ("RATE_LIMIT", "MiniMax 限流，请稍后重试。"),
    1004: ("AUTH_FAILED", "MiniMax 鉴权失败，请检查 API Key。"),
    1008: ("INSUFFICIENT_BALANCE", "MiniMax 账户余额不足。"),
    1026: ("CONTENT_POLICY", "MiniMax 内容限制，请调整提示词。"),
    2013: ("INVALID_PARAMS", "MiniMax 参数错误。"),
    2049: ("INVALID_API_KEY", "MiniMax API Key 无效。"),
}


@dataclass
class ParsedMinimaxImageResponse:
    ok: bool
    images: list[str]
    business_status: int | None
    business_message: str | None
    success_count: int | None
    internal_code: str
    user_message: str


def normalize_prompt_text(prompt: str) -> str:
    """Single definition of effective prompt text (Python len, all Unicode code points)."""
    return re.sub(r"\s+", " ", (prompt or "").strip())


def prompt_char_count(prompt: str) -> int:
    return len(normalize_prompt_text(prompt))


def validate_effective_prompt(prompt: str, *, stage: str = "api") -> str:
    normalized = normalize_prompt_text(prompt)
    if not normalized:
        raise ValueError(f"COVER_PROMPT_EMPTY:{stage}")
    count = len(normalized)
    if count > MAX_PROMPT_CHARS:
        raise ValueError(f"COVER_PROMPT_TOO_LONG:{count}:{MAX_PROMPT_CHARS}:{stage}")
    return normalized


def assert_default_prompt_budget(prompt: str) -> None:
    count = prompt_char_count(prompt)
    if count > DEFAULT_PROMPT_TARGET_CHARS:
        raise ValueError(f"COVER_DEFAULT_PROMPT_TOO_LONG:{count}:{DEFAULT_PROMPT_TARGET_CHARS}")


def clamp_prompt(prompt: str) -> str:
    """Legacy helper; prefer validate_effective_prompt. Never silently extend beyond MAX."""
    normalized = normalize_prompt_text(prompt)
    if len(normalized) <= MAX_PROMPT_CHARS:
        return normalized
    return normalized[:MAX_PROMPT_CHARS]


def map_business_status(status_code: int | None, fallback_msg: str | None = None) -> tuple[str, str]:
    if status_code is None:
        return "MINIMAX_API_ERROR", fallback_msg or "MiniMax 返回异常。"
    mapped = MINIMAX_STATUS_MAP.get(int(status_code))
    if mapped:
        return mapped
    return f"MINIMAX_{status_code}", fallback_msg or f"MiniMax 业务错误（{status_code}）。"


def parse_image_generation_body(body: dict[str, Any]) -> ParsedMinimaxImageResponse:
    base = body.get("base_resp") if isinstance(body, dict) else None
    status_code = None
    status_msg = None
    if isinstance(base, dict):
        raw_code = base.get("status_code")
        if raw_code is not None:
            try:
                status_code = int(raw_code)
            except (TypeError, ValueError):
                status_code = None
        status_msg = base.get("status_msg") if base.get("status_msg") is not None else None

    if status_code not in (None, 0):
        code, message = map_business_status(status_code, str(status_msg) if status_msg else None)
        return ParsedMinimaxImageResponse(
            ok=False,
            images=[],
            business_status=status_code,
            business_message=str(status_msg) if status_msg else None,
            success_count=None,
            internal_code=code,
            user_message=message,
        )

    metadata = body.get("metadata") if isinstance(body, dict) else None
    success_count = None
    if isinstance(metadata, dict) and metadata.get("success_count") is not None:
        try:
            success_count = int(metadata["success_count"])
        except (TypeError, ValueError):
            success_count = 0
    if success_count is not None and success_count < 1:
        code, message = map_business_status(status_code, "未生成任何图片。")
        return ParsedMinimaxImageResponse(
            ok=False,
            images=[],
            business_status=status_code,
            business_message=status_msg,
            success_count=success_count,
            internal_code="NO_IMAGE",
            user_message=message,
        )

    data = body.get("data") if isinstance(body, dict) else None
    images_raw = data.get("image_base64") if isinstance(data, dict) else None
    if not isinstance(images_raw, list) or not images_raw:
        return ParsedMinimaxImageResponse(
            ok=False,
            images=[],
            business_status=status_code,
            business_message=status_msg,
            success_count=success_count,
            internal_code="NO_IMAGE",
            user_message="响应中没有图片（image_base64 为空）。",
        )
    images = [str(item) for item in images_raw if item]
    if not images:
        return ParsedMinimaxImageResponse(
            ok=False,
            images=[],
            business_status=status_code,
            business_message=status_msg,
            success_count=success_count,
            internal_code="NO_IMAGE",
            user_message="响应中没有有效图片数据。",
        )

    return ParsedMinimaxImageResponse(
        ok=True,
        images=images,
        business_status=status_code if status_code is not None else 0,
        business_message=str(status_msg) if status_msg else None,
        success_count=success_count,
        internal_code="OK",
        user_message="",
    )
