"""Bounded HTTP retry backoff for cloud LLM providers."""

from __future__ import annotations

import random
import time

MAX_BACKOFF_SECONDS = 8.0


def sleep_before_retry(*, attempt: int, status_code: int, retry_after_header: str | None) -> None:
    if retry_after_header and retry_after_header.strip().isdigit():
        delay = min(float(retry_after_header.strip()), MAX_BACKOFF_SECONDS)
    elif status_code == 429:
        delay = min(2.0 * (2**attempt), MAX_BACKOFF_SECONDS)
    else:
        base = 0.5 * (2**attempt)
        delay = min(base + random.uniform(0, 0.35), MAX_BACKOFF_SECONDS)
    time.sleep(max(0.05, delay))
