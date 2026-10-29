"""Limit concurrent outbound calls per provider type (Redis semaphore)."""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager

from redis import Redis

from app.core.config import Settings, get_settings

_KEY_PREFIX = "insighthub:llm:inflight:"
_DEFAULT_LIMITS = {
    "ZAI": 2,
    "SILICONFLOW": 2,
    "DEEPSEEK": 2,
}


@contextmanager
def provider_call_slot(provider_type: str, *, settings: Settings | None = None, timeout_seconds: float = 120):
    settings = settings or get_settings()
    limit = _DEFAULT_LIMITS.get(provider_type, 3)
    token = str(uuid.uuid4())
    redis = Redis.from_url(settings.redis_url)
    key = f"{_KEY_PREFIX}{provider_type}"
    deadline = time.monotonic() + timeout_seconds
    acquired = False
    try:
        while time.monotonic() < deadline:
            current = int(redis.scard(key) or 0)
            if current < limit:
                redis.sadd(key, token)
                redis.expire(key, 300)
                acquired = True
                break
            time.sleep(0.25)
        if not acquired:
            from app.services.llm.types import LLMError

            raise LLMError("PROVIDER_UNAVAILABLE", "模型服务并发已满，请稍后重试。")
        yield
    finally:
        if acquired:
            redis.srem(key, token)
