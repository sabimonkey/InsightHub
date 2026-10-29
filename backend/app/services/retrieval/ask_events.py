"""Ephemeral Ask turn events via Redis Streams (SSE transport)."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Iterator

import redis

from app.core.config import Settings, get_settings

STREAM_PREFIX = "insighthub:ask:stream:"


def stream_key(turn_id: uuid.UUID | str) -> str:
    return f"{STREAM_PREFIX}{turn_id}"


class AskTurnEventPublisher:
    def __init__(self, turn_id: uuid.UUID, settings: Settings | None = None) -> None:
        self.turn_id = turn_id
        self.settings = settings or get_settings()
        self._client = redis.Redis.from_url(self.settings.redis_url, decode_responses=True)
        self._key = stream_key(turn_id)
        self._sequence = 0
        self._ttl_set = False

    def publish(self, event: str, payload: dict[str, Any] | None = None) -> str | None:
        body = json.dumps(payload or {}, ensure_ascii=False)
        entry_id = self._client.xadd(self._key, {"event": event, "payload": body})
        if not self._ttl_set:
            self._client.expire(self._key, int(self.settings.ask_stream_ttl_seconds))
            self._ttl_set = True
        return entry_id

    def heartbeat(self) -> None:
        self.publish("heartbeat", {})

    def delta(self, text: str) -> None:
        if not text:
            return
        self._sequence += 1
        self.publish("delta", {"sequence": self._sequence, "text": text})

    def close(self) -> None:
        self._client.close()


def read_stream_entries(
    turn_id: uuid.UUID | str,
    last_id: str = "0-0",
    *,
    block_ms: int = 0,
    count: int = 100,
    settings: Settings | None = None,
) -> list[tuple[str, str, dict[str, Any]]]:
    settings = settings or get_settings()
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    key = stream_key(turn_id)
    try:
        if block_ms > 0:
            rows = client.xread({key: last_id}, block=block_ms, count=count)
        else:
            rows = client.xread({key: last_id}, count=count)
    finally:
        client.close()
    if not rows:
        return []
    entries: list[tuple[str, str, dict[str, Any]]] = []
    for _stream, items in rows:
        for entry_id, fields in items:
            event = fields.get("event") or "message"
            try:
                payload = json.loads(fields.get("payload") or "{}")
            except json.JSONDecodeError:
                payload = {}
            entries.append((entry_id, event, payload))
    return entries


def iter_sse_events(
    turn_id: uuid.UUID,
    *,
    last_event_id: str | None = None,
    settings: Settings | None = None,
    terminal_statuses: frozenset[str] = frozenset({"SUCCEEDED", "PARTIAL", "FAILED", "NO_EVIDENCE"}),
    get_turn_status,
) -> Iterator[str]:
    """Yield SSE lines (event + data) until final/error or turn terminal in DB."""
    settings = settings or get_settings()
    cursor = last_event_id or "0-0"
    last_heartbeat = time.monotonic()
    while True:
        status = get_turn_status()
        if status in terminal_statuses and cursor != "0-0":
            # allow one more read for final event
            pass
        entries = read_stream_entries(turn_id, cursor, block_ms=1500, count=50, settings=settings)
        if not entries:
            if time.monotonic() - last_heartbeat > 20:
                yield _format_sse(None, "heartbeat", {})
                last_heartbeat = time.monotonic()
            status = get_turn_status()
            if status in terminal_statuses:
                break
            continue
        for entry_id, event, payload in entries:
            cursor = entry_id
            yield _format_sse(entry_id, event, payload)
            if event in {"final", "error"}:
                return
        status = get_turn_status()
        if status in terminal_statuses and not any(e[1] == "final" for e in entries):
            # worker finished without final event (inline / no publisher)
            break


def _format_sse(entry_id: str | None, event: str, payload: dict[str, Any]) -> str:
    lines = []
    if entry_id:
        lines.append(f"id: {entry_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(payload, ensure_ascii=False)}")
    lines.append("")
    return "\n".join(lines) + "\n"
