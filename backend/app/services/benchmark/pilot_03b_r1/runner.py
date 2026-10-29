"""Execute V1.0-PILOT-03B-R1 cloud model benchmark."""

from __future__ import annotations

import json
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT, Settings, get_settings
from app.db.session import get_sessionmaker
from app.services.analysis.service import AnalysisService
from app.services.benchmark.pilot_03b_r1.ask_runner import answer_from_packet, build_retrieval_packet, run_planner
from app.services.benchmark.pilot_03b_r1.audit import audit_providers
from app.services.benchmark.pilot_03b_r1.brief_runner import capture_brief_packets, run_brief_with_packets
from app.services.benchmark.pilot_03b_r1.constants import (
    ANALYSIS_RUNS_PER_SOURCE,
    ASK_QUERIES,
    ASK_RUNS_PER_QUERY,
    BENCHMARK_NAME,
    BRIEF_CASES,
    BRIEF_RUNS_PER_CASE,
    CORPUS_CASES,
    PLANNER_QUERIES,
    PLANNER_RUNS_PER_QUERY,
    PROVIDER_DEEPSEEK,
    PROVIDER_GLM,
)
from app.services.benchmark.pilot_03b_r1.corpus import bench_settings, chunk_text_map, ensure_clone
from app.services.benchmark.pilot_03b_r1.metrics import analysis_run_metrics
from app.services.benchmark.pilot_03b_r1.report import build_report, write_report
from app.services.llm.provider import LocalOpenAICompatibleProvider
from app.services.llm.routing import list_routes, update_routes


def _manifest_tmp(root: Path) -> Path:
    return root / "manifest.json.tmp"


def _cleanup_stale_manifest_files(root: Path) -> None:
    for name in ("manifest.json.tmp", "manifest.partial.json"):
        path = root / name
        if path.exists():
            path.unlink()


def _checkpoint(root: Path, manifest: dict) -> None:
    _manifest_tmp(root).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True).strip()
    except Exception:
        return "unknown"


def _artifact_root() -> Path:
    return PROJECT_ROOT / "artifacts" / "benchmarks" / BENCHMARK_NAME


def run_analysis(session: Session, settings: Settings, manifest: dict) -> None:
    local_calls = {"count": 0}
    original = LocalOpenAICompatibleProvider.complete

    def _track(self, request):
        local_calls["count"] += 1
        return original(self, request)

    LocalOpenAICompatibleProvider.complete = _track
    auto = bench_settings(settings)
    clones: dict[str, str] = {}
    manifest["analysis"] = []
    try:
        for case in CORPUS_CASES:
            user_id = uuid.UUID(case["user_source_id"])
            clone_id = ensure_clone(session, settings, user_id, case["case_id"])
            clones[case["case_id"]] = str(clone_id)
            chunks = chunk_text_map(session, clone_id)
            for provider in (PROVIDER_DEEPSEEK, PROVIDER_GLM):
                for run_index in range(ANALYSIS_RUNS_PER_SOURCE):
                    started = time.perf_counter()
                    run = AnalysisService(session, inline=True, settings=auto).start(clone_id, provider)
                    metrics = analysis_run_metrics(session, run, chunks)
                    metrics.update(
                        {
                            "benchmark_case_id": case["case_id"],
                            "user_source_id": case["user_source_id"],
                            "clone_source_id": str(clone_id),
                            "provider_candidate": provider,
                            "run_index": run_index + 1,
                            "wall_s": round(time.perf_counter() - started, 1),
                        }
                    )
                    manifest["analysis"].append(metrics)
    finally:
        LocalOpenAICompatibleProvider.complete = original
    manifest["analysis_clone_map"] = clones
    manifest["analysis_local_calls"] = local_calls["count"]


def run_planner_benchmark(session: Session, settings: Settings, manifest: dict) -> None:
    rows = []
    for item in PLANNER_QUERIES:
        for provider in (PROVIDER_DEEPSEEK, PROVIDER_GLM):
            for run_index in range(PLANNER_RUNS_PER_QUERY):
                result = run_planner(session, settings, item["text"], provider)
                result.update(
                    {
                        "query_id": item["id"],
                        "expected_mode": item["expected"],
                        "mode_correct": result.get("mode") == item["expected"],
                        "run_index": run_index + 1,
                    }
                )
                rows.append(result)
    manifest["planner"] = rows


def run_ask_benchmark(session: Session, settings: Settings, manifest: dict) -> None:
    packets = {}
    for item in ASK_QUERIES:
        packets[item["id"]] = build_retrieval_packet(session, settings, item["text"], PROVIDER_GLM)
    manifest["ask_packets"] = {key: {"question": value["question"], "chunk_count": len(value["context"])} for key, value in packets.items()}
    rows = []
    for item in ASK_QUERIES:
        packet = packets[item["id"]]
        for provider in (PROVIDER_DEEPSEEK, PROVIDER_GLM):
            for run_index in range(ASK_RUNS_PER_QUERY):
                result = answer_from_packet(session, settings, packet, provider)
                result.update({"query_id": item["id"], "run_index": run_index + 1})
                rows.append(result)
    manifest["ask_answer"] = rows


def run_brief_benchmark(session: Session, settings: Settings, manifest: dict) -> None:
    rows = []
    for case in BRIEF_CASES:
        filters = dict(case["filters"])
        packets, included, preview = capture_brief_packets(session, settings, filters)
        manifest.setdefault("brief_packets", {})[case["case_id"]] = preview
        for provider in (PROVIDER_DEEPSEEK, PROVIDER_GLM):
            for run_index in range(BRIEF_RUNS_PER_CASE):
                result = run_brief_with_packets(session, settings, filters, packets, included, provider)
                result.update({"case_id": case["case_id"], "run_index": run_index + 1, "provider_candidate": provider})
                rows.append(result)
    manifest["brief"] = rows


def run_benchmark(phases: list[str] | None = None) -> Path:
    settings = get_settings()
    session = get_sessionmaker()()
    root = _artifact_root()
    root.mkdir(parents=True, exist_ok=True)
    _cleanup_stale_manifest_files(root)
    manifest: dict = {
        "benchmark_name": BENCHMARK_NAME,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "commit": _git_head(),
        "routes": list_routes(session, settings),
        "providers": audit_providers(session, settings),
    }
    wanted = set(phases or ["analysis", "planner", "ask", "brief"])
    if "analysis" in wanted:
        run_analysis(session, settings, manifest)
        _checkpoint(root, manifest)
    if "planner" in wanted:
        run_planner_benchmark(session, settings, manifest)
        _checkpoint(root, manifest)
    if "ask" in wanted:
        run_ask_benchmark(session, settings, manifest)
        _checkpoint(root, manifest)
    if "brief" in wanted:
        run_brief_benchmark(session, settings, manifest)
        _checkpoint(root, manifest)
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    report = build_report(manifest)
    manifest["report"] = report
    changes = report.get("route_changes") or {}
    if changes and changes.get("status") != "NO_CHANGE":
        update_routes(session, settings, report["routing_decision"])
        manifest["routes_after"] = list_routes(session, settings)
    write_report(root, manifest, report)
    session.close()
    return root


if __name__ == "__main__":
    import sys

    phases = sys.argv[1:] if len(sys.argv) > 1 else None
    path = run_benchmark(phases)
    print(path)
