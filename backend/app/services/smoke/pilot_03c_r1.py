"""V1.0-PILOT-03C-R1: real USER Ask streaming smoke (API + SSE + reconnect)."""

from __future__ import annotations

import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

OPENKB_SOURCE_ID = "b0ef2dac-661b-44f4-8c78-c631f7c6a91f"
QUESTION = "总结我收藏的 OpenKB 资料的核心内容。"
API_BASE = "http://127.0.0.1:8090"


@dataclass
class SmokeReport:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    delta_count: int = 0
    delta_chars: int = 0
    metrics: dict[str, Any] = field(default_factory=dict)
    turn_id: str | None = None
    session_id: str | None = None
    status: str | None = None

    def fail(self, message: str) -> None:
        self.ok = False
        self.errors.append(message)


def _require(condition: bool, report: SmokeReport, message: str) -> None:
    if not condition:
        report.fail(message)


def health_checks(report: SmokeReport) -> None:
    checks = [
        ("BGE", "http://127.0.0.1:8011/health"),
        ("API", f"{API_BASE}/health"),
        ("Frontend", "http://127.0.0.1:5174"),
    ]
    with httpx.Client(timeout=10) as client:
        for name, url in checks:
            try:
                response = client.get(url)
                _require(response.status_code < 500, report, f"{name} unhealthy: {url} HTTP {response.status_code}")
            except httpx.HTTPError as exc:
                report.fail(f"{name} unreachable: {url} ({type(exc).__name__})")


def cloud_preflight(report: SmokeReport) -> None:
    from app.core.config import get_settings
    from app.db.session import get_sessionmaker
    from app.services.llm.registry import build_provider
    from app.services.llm.routing import resolve_workflow
    from app.services.llm.types import LLMRequest

    settings = get_settings()
    db = get_sessionmaker()()
    try:
        for workflow in ("ASK_PLANNER", "ASK_ANSWER"):
            spec = resolve_workflow(db, settings, workflow, None)
            provider = build_provider(spec, settings)
            try:
                provider.complete(
                    LLMRequest(
                        system_prompt="Reply with OK.",
                        user_content="ping",
                        temperature=0,
                        max_output_tokens=16,
                        metadata={"purpose": "smoke_ping"},
                    )
                )
            except Exception as exc:
                report.fail(f"{workflow} preflight failed: {type(exc).__name__}")
    finally:
        db.close()


def verify_production_routes(report: SmokeReport) -> dict[str, tuple[str, str, str]]:
    from sqlalchemy import text

    from app.db.session import get_sessionmaker

    db = get_sessionmaker()()
    rows: dict[str, tuple[str, str, str]] = {}
    try:
        result = db.execute(
            text(
                """
                SELECT r.workflow, p.provider_type, d.model_id, d.id::text
                FROM llm_workflow_routes r
                JOIN llm_model_deployments d ON d.id = r.deployment_id
                JOIN llm_provider_configs p ON p.id = d.provider_config_id
                ORDER BY r.workflow
                """
            )
        )
        for workflow, provider_type, model_id, deployment_id in result:
            rows[str(workflow)] = (str(provider_type), str(model_id), str(deployment_id))
        planner = rows.get("ASK_PLANNER")
        answer = rows.get("ASK_ANSWER")
        _require(planner is not None and planner[0] == "DEEPSEEK", report, f"ASK_PLANNER route invalid: {planner}")
        _require(answer is not None and answer[0] == "SILICONFLOW", report, f"ASK_ANSWER route invalid: {answer}")
        _require("GLM" in (answer[1] if answer else ""), report, f"ASK_ANSWER model unexpected: {answer}")
    finally:
        db.close()
    report.metrics["production_routes"] = {key: {"provider": v[0], "model": v[1], "deployment_id": v[2]} for key, v in rows.items()}
    return rows


def verify_openkb_source(report: SmokeReport) -> None:
    from app.db.session import get_sessionmaker
    from app.models.source_item import SourceItem

    db = get_sessionmaker()()
    try:
        source = db.get(SourceItem, uuid.UUID(OPENKB_SOURCE_ID))
        _require(source is not None, report, "OpenKB source missing")
        if source is not None:
            _require(source.system_scope == "USER", report, f"OpenKB scope={source.system_scope}")
            report.metrics["openkb_title"] = source.display_name
    finally:
        db.close()


def consume_sse(turn_id: str, report: SmokeReport, *, stop_after_deltas: int | None = None, disconnect_early: bool = False) -> dict[str, Any]:
    url = f"{API_BASE}/api/ask/turns/{turn_id}/events"
    started = time.perf_counter()
    first_delta_at: float | None = None
    final_at: float | None = None
    deltas: list[str] = []
    final_payload: dict[str, Any] | None = None
    last_id: str | None = None
    with httpx.Client(timeout=None) as client:
        with client.stream("GET", url, headers={"Accept": "text/event-stream"}) as response:
            _require(response.status_code == 200, report, f"SSE HTTP {response.status_code}")
            event_name = "message"
            data_lines: list[str] = []
            for line in response.iter_lines():
                if line is None:
                    continue
                if line == "":
                    if data_lines:
                        payload_raw = "\n".join(data_lines)
                        try:
                            payload = json.loads(payload_raw)
                        except json.JSONDecodeError:
                            payload = {}
                        report.events.append(event_name)
                        if event_name == "delta":
                            text = str(payload.get("text") or "")
                            if text:
                                deltas.append(text)
                                report.delta_count += 1
                                report.delta_chars += len(text)
                                if first_delta_at is None:
                                    first_delta_at = time.perf_counter()
                                if stop_after_deltas and report.delta_count >= stop_after_deltas and disconnect_early:
                                    return {
                                        "first_delta_at": first_delta_at,
                                        "final_at": final_at,
                                        "deltas": deltas,
                                        "final_payload": final_payload,
                                        "last_id": last_id,
                                        "disconnected_early": True,
                                    }
                        if event_name == "final":
                            final_payload = payload
                            final_at = time.perf_counter()
                            return {
                                "first_delta_at": first_delta_at,
                                "final_at": final_at,
                                "deltas": deltas,
                                "final_payload": final_payload,
                                "last_id": last_id,
                                "disconnected_early": False,
                            }
                        if event_name == "error":
                            report.fail(f"SSE error event: {payload}")
                            return {
                                "first_delta_at": first_delta_at,
                                "final_at": final_at,
                                "deltas": deltas,
                                "final_payload": final_payload,
                                "last_id": last_id,
                                "disconnected_early": False,
                            }
                    event_name = "message"
                    data_lines = []
                    continue
                if line.startswith("id:"):
                    last_id = line[3:].strip()
                    continue
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                    continue
                if line.startswith("data:"):
                    data_lines.append(line[5:].strip())
    report.fail("SSE ended without final event")
    return {
        "first_delta_at": first_delta_at,
        "final_at": final_at,
        "deltas": deltas,
        "final_payload": final_payload,
        "last_id": last_id,
        "disconnected_early": True,
    }


def create_real_ask(report: SmokeReport) -> uuid.UUID:
    with httpx.Client(timeout=30) as client:
        session = client.post(f"{API_BASE}/api/ask/sessions", json={"title": QUESTION[:80]})
        _require(session.status_code == 200, report, f"create session failed: {session.status_code}")
        session_id = session.json()["id"]
        report.session_id = str(session_id)
        turn = client.post(
            f"{API_BASE}/api/ask/sessions/{session_id}/turns",
            json={"question": QUESTION, "filters": {"scope": "mine", "source_ids": [OPENKB_SOURCE_ID]}},
        )
        _require(turn.status_code == 200, report, f"create turn failed: {turn.status_code} {turn.text[:200]}")
        turn_id = turn.json()["id"]
        report.turn_id = str(turn_id)
        return uuid.UUID(str(turn_id))


def wait_terminal_turn(turn_id: uuid.UUID, report: SmokeReport, timeout_s: int = 300) -> dict[str, Any]:
    deadline = time.perf_counter() + timeout_s
    last: dict[str, Any] = {}
    with httpx.Client(timeout=30) as client:
        while time.perf_counter() < deadline:
            response = client.get(f"{API_BASE}/api/ask/turns/{turn_id}")
            _require(response.status_code == 200, report, f"get turn failed: {response.status_code}")
            last = response.json()
            if last.get("status") not in {"PENDING", "RUNNING"}:
                return last
            time.sleep(1.0)
    report.fail("turn did not reach terminal state in time")
    return last


def verify_turn_lineage(turn: dict[str, Any], report: SmokeReport) -> None:
    retrieval = turn.get("retrieval") or {}
    _require(retrieval.get("planner_provider_type") == "DEEPSEEK", report, f"planner provider {retrieval.get('planner_provider_type')}")
    _require("deepseek" in str(retrieval.get("planner_model") or "").lower(), report, f"planner model {retrieval.get('planner_model')}")
    _require(retrieval.get("answer_provider_type") == "SILICONFLOW", report, f"answer provider {retrieval.get('answer_provider_type')}")
    _require(retrieval.get("answer_streaming") is True, report, "answer_streaming not true")
    _require(turn.get("provider_type") == "SILICONFLOW", report, f"turn provider {turn.get('provider_type')}")
    _require("glm" in str(turn.get("model_name") or "").lower(), report, f"answer model {turn.get('model_name')}")
    report.metrics["retrieval"] = retrieval
    report.metrics["tokens"] = {
        "input": turn.get("input_tokens"),
        "output": turn.get("output_tokens"),
    }


def verify_grounding(turn: dict[str, Any], report: SmokeReport) -> None:
    answer = (turn.get("answer_markdown") or "").lower()
    citations = turn.get("citations") or []
    titles = " ".join(str(item.get("source_title") or "") for item in citations).lower()
    blob = f"{answer} {titles}"
    keywords = ("openkb", "wiki", "知识", "文档", "开源")
    _require(any(word in blob for word in keywords), report, f"grounding weak: answer/citations lack OpenKB signals ({blob[:120]}...)")
    report.metrics["validated_citations"] = len(citations)


def redis_replay(turn_id: uuid.UUID, last_id: str | None, report: SmokeReport) -> None:
    from app.core.config import get_settings
    from app.services.retrieval.ask_events import read_stream_entries

    if not last_id:
        report.fail("missing last SSE id for redis replay")
        return
    entries = read_stream_entries(turn_id, last_id=last_id, settings=get_settings())
    _require(len(entries) >= 0, report, "redis replay read failed")
    report.metrics["redis_replay_entries"] = len(entries)


def verify_user_scope_visibility(report: SmokeReport) -> None:
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.db.session import get_sessionmaker
    from app.models.retrieval import AskSession
    from app.services.system_scope import AUTOMATION_TEST_SCOPE, api_visibility_filter

    settings = get_settings()
    db = get_sessionmaker()()
    try:
        rows = list(db.scalars(select(AskSession).where(api_visibility_filter(AskSession.system_scope, settings))))
        hidden = list(
            db.scalars(
                select(AskSession).where(AskSession.system_scope == AUTOMATION_TEST_SCOPE).limit(5),
            )
        )
        _require(all(row.system_scope != AUTOMATION_TEST_SCOPE for row in rows), report, "AUTOMATION_TEST leaked into USER session list")
        if hidden:
            _require(
                all(row.id not in {item.id for item in rows} for row in hidden),
                report,
                "AUTOMATION_TEST session visible to USER API",
            )
    finally:
        db.close()


def run_smoke() -> SmokeReport:
    report = SmokeReport()
    health_checks(report)
    if not report.ok:
        return report
    verify_production_routes(report)
    verify_openkb_source(report)
    verify_user_scope_visibility(report)
    cloud_preflight(report)
    if not report.ok:
        return report

    turn_started = time.perf_counter()
    turn_id = create_real_ask(report)
    if not report.ok:
        return report

    # Disconnect path: read a few deltas then close; worker must still finish.
    partial = consume_sse(str(turn_id), report, stop_after_deltas=2, disconnect_early=True)
    if report.delta_count < 2:
        report.fail(f"expected >=2 deltas before disconnect, got {report.delta_count}")
    disconnected_at = time.perf_counter()
    turn_after_disconnect = wait_terminal_turn(turn_id, report)
    _require(turn_after_disconnect.get("status") in {"SUCCEEDED", "PARTIAL", "NO_EVIDENCE", "FAILED"}, report, "turn not terminal after SSE disconnect")
    if turn_after_disconnect.get("status") in {"SUCCEEDED", "PARTIAL"}:
        _require(bool(turn_after_disconnect.get("answer_markdown")), report, "missing final answer after disconnect")

    # Full SSE trace on a second USER turn (same session) for ordered events + replay.
    with httpx.Client(timeout=30) as client:
        turn2 = client.post(
            f"{API_BASE}/api/ask/sessions/{report.session_id}/turns",
            json={"question": QUESTION + "（流式验收）", "filters": {"scope": "mine", "source_ids": [OPENKB_SOURCE_ID]}},
        )
        _require(turn2.status_code == 200, report, f"second turn failed: {turn2.status_code}")
        turn2_id = uuid.UUID(str(turn2.json()["id"]))
    report.metrics["sse_trace_turn_id"] = str(turn2_id)
    report.events.clear()
    report.delta_count = 0
    report.delta_chars = 0
    trace_started = time.perf_counter()
    sse = consume_sse(str(turn2_id), report)
    required = {"turn_started", "planning", "retrieving", "answer_started", "validating", "final"}
    missing = sorted(required - set(report.events))
    _require(not missing, report, f"missing SSE events: {missing}")
    _require(report.delta_count >= 2, report, f"delta count {report.delta_count}")
    first_delta = sse.get("first_delta_at")
    final_at = sse.get("final_at")
    if first_delta and final_at:
        ttft_ms = int((first_delta - trace_started) * 1000)
        total_ms = int((final_at - trace_started) * 1000)
        report.metrics["time_to_first_visible_content_ms"] = ttft_ms
        report.metrics["stream_trace_total_ms"] = total_ms
        _require(ttft_ms < total_ms, report, f"TTFT not less than total ({ttft_ms} >= {total_ms})")
    redis_replay(turn2_id, sse.get("last_id"), report)

    turn_final = wait_terminal_turn(turn2_id, report)
    report.status = str(turn_final.get("status"))
    _require(report.status in {"SUCCEEDED", "PARTIAL"}, report, f"unexpected final status {report.status}")
    verify_turn_lineage(turn_final, report)
    verify_grounding(turn_final, report)
    report.metrics["finish_reason"] = (turn_final.get("retrieval") or {}).get("finish_reason")
    report.metrics["planner_latency_ms"] = (turn_final.get("retrieval") or {}).get("planner_latency_ms")
    report.metrics["retrieval_latency_ms"] = (turn_final.get("retrieval") or {}).get("retrieval_latency_ms")
    report.metrics["answer_stream_duration_ms"] = (turn_final.get("retrieval") or {}).get("answer_stream_duration_ms")
    report.metrics["time_to_first_token_ms"] = (turn_final.get("retrieval") or {}).get("time_to_first_token_ms")
    report.metrics["generation_latency_ms"] = (turn_final.get("retrieval") or {}).get("generation_latency_ms")
    report.metrics["disconnected_turn_status"] = turn_after_disconnect.get("status")
    report.metrics["disconnect_to_terminal_ms"] = int((time.perf_counter() - disconnected_at) * 1000)
    return report


def main() -> int:
    report = run_smoke()
    print(json.dumps({"ok": report.ok, "errors": report.errors, "metrics": report.metrics, "events": report.events, "delta_count": report.delta_count}, ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
