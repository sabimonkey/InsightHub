"""Execute paired DeepSeek vs GLM analysis benchmark on AUTOMATION_TEST clones."""

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
from app.services.benchmark.pilot_03b_r1.corpus import bench_settings, chunk_text_map, ensure_clone
from app.services.benchmark.pilot_03b_r1.metrics import aggregate_numeric, analysis_run_metrics, median
from app.services.benchmark.pipeline_r1.pricing import (
    DEEPSEEK_V4_PRO,
    GLM_53_FLASH,
    estimate_call_usd,
    usd_to_cny,
)
from app.services.benchmark.pipeline_r1.selection import SampleCandidate, budget_estimate_cny, list_eligible, pick_samples

BENCHMARK_NAME = "pipeline_r1"
PROVIDERS = ("DEEPSEEK", "SILICONFLOW")
CNY_CAP = 20.0


def artifact_root() -> Path:
    root = PROJECT_ROOT / "artifacts" / "benchmarks" / BENCHMARK_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def manifest_path() -> Path:
    return artifact_root() / "manifest.json"


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True).strip()
    except Exception:
        return "unknown"


def _load_manifest() -> dict:
    path = manifest_path()
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_manifest(manifest: dict) -> None:
    path = manifest_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _actual_cost_cny(run_metrics: dict, provider: str) -> float:
    inp = int(run_metrics.get("prompt_tokens") or 0)
    out = int(run_metrics.get("completion_tokens") or 0)
    pricing = DEEPSEEK_V4_PRO if provider == "DEEPSEEK" else GLM_53_FLASH
    return usd_to_cny(estimate_call_usd(pricing, input_tokens=inp, output_tokens=out))


def prepare_manifest(session: Session, settings: Settings, *, total_samples: int = 12) -> dict:
    candidates = list_eligible(session, settings)
    picked = pick_samples(candidates, total_samples)
    if len(picked) < total_samples:
        raise RuntimeError(f"INSUFFICIENT_SAMPLES: need {total_samples}, got {len(picked)}")
    est = budget_estimate_cny(picked)
    if est["total_est_cny"] > CNY_CAP:
        raise RuntimeError(f"BUDGET_ESTIMATE_EXCEEDS_CAP: {est['total_est_cny']} CNY > {CNY_CAP}")
    manifest = _load_manifest()
    manifest.update(
        {
            "benchmark_name": BENCHMARK_NAME,
            "contract": "source_analysis 1.1.0",
            "git_head": _git_head(),
            "prepared_at": datetime.now(timezone.utc).isoformat(),
            "cny_cap": CNY_CAP,
            "budget_estimate": est,
            "samples": [
                {
                    "case_id": f"s{i+1}",
                    "user_source_id": str(row.source_id),
                    "title": row.title,
                    "char_count": row.char_count,
                    "tags": row.tags,
                    "language_hint": row.language_hint,
                    "had_analysis_failure": row.had_analysis_failure,
                }
                for i, row in enumerate(picked)
            ],
            "runs": manifest.get("runs") or [],
            "spent_cny": manifest.get("spent_cny") or 0.0,
        }
    )
    _save_manifest(manifest)
    return manifest


def _run_one(session: Session, settings: Settings, case: dict, provider: str, spent: float) -> tuple[dict, float]:
    auto = bench_settings(settings.model_copy(update={"llm_provider_fallback_enabled": False}))
    user_id = uuid.UUID(case["user_source_id"])
    clone_id = ensure_clone(session, settings, user_id, case["case_id"])
    session.commit()
    # wait for inline extraction on clone
    for _ in range(60):
        chunks = chunk_text_map(session, clone_id)
        if chunks:
            break
        time.sleep(0.5)
    chunks = chunk_text_map(session, clone_id)
    if not chunks:
        raise RuntimeError(f"CLONE_EXTRACTION_EMPTY:{case['case_id']}")
    started = time.perf_counter()
    run = AnalysisService(session, inline=True, settings=auto).start(clone_id, provider)
    metrics = analysis_run_metrics(session, run, chunks)
    wall_s = round(time.perf_counter() - started, 2)
    cost = _actual_cost_cny(metrics, provider)
    if spent + cost > CNY_CAP:
        raise RuntimeError(f"BUDGET_CAP_EXCEEDED: projected {spent + cost:.2f} CNY")
    metrics.update(
        {
            "benchmark_case_id": case["case_id"],
            "user_source_id": case["user_source_id"],
            "clone_source_id": str(clone_id),
            "provider_candidate": provider,
            "wall_s": wall_s,
            "est_cost_cny": round(cost, 4),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return metrics, spent + cost


def run_batch(batch: str) -> dict:
    """batch: pilot (first 4 cases) | remainder (rest)."""
    settings = get_settings()
    session = get_sessionmaker()()
    try:
        manifest = prepare_manifest(session, settings) if not manifest_path().exists() else _load_manifest()
        if not manifest.get("samples"):
            manifest = prepare_manifest(session, settings)
        samples = manifest["samples"]
        if batch == "pilot":
            batch_samples = samples[:4]
        elif batch == "remainder":
            batch_samples = samples[4:12]
        else:
            raise ValueError("batch must be pilot or remainder")
        spent = float(manifest.get("spent_cny") or 0.0)
        runs: list[dict] = list(manifest.get("runs") or [])
        existing = {(r["benchmark_case_id"], r["provider_candidate"]) for r in runs}
        for case in batch_samples:
            for provider in PROVIDERS:
                key = (case["case_id"], provider)
                if key in existing:
                    continue
                metrics, spent = _run_one(session, settings, case, provider, spent)
                runs.append(metrics)
                manifest["runs"] = runs
                manifest["spent_cny"] = round(spent, 4)
                _save_manifest(manifest)
        manifest["last_batch"] = batch
        manifest["batch_completed_at"] = datetime.now(timezone.utc).isoformat()
        _save_manifest(manifest)
        return manifest
    finally:
        session.close()


def pilot_gate_ok(manifest: dict) -> bool:
    runs = [r for r in manifest.get("runs") or [] if r.get("benchmark_case_id", "").startswith("s") and int(r["benchmark_case_id"][1:]) <= 4]
    if len(runs) < 8:
        return False
    for row in runs:
        if row.get("provider_candidate") == "DEEPSEEK" and row.get("model") != DEEPSEEK_V4_PRO.model_id:
            continue
        if not row.get("http_success"):
            return False
        if not row.get("parse_success"):
            return False
    return True


def build_gate_b_report(manifest: dict) -> dict:
    runs = manifest.get("runs") or []
    by_provider: dict[str, list] = {}
    for row in runs:
        by_provider.setdefault(row.get("provider_candidate") or "?", []).append(row)
    pairs = []
    samples = {s["case_id"]: s for s in manifest.get("samples") or []}
    for case_id in sorted(samples):
        ds = next((r for r in runs if r.get("benchmark_case_id") == case_id and r.get("provider_candidate") == "DEEPSEEK"), None)
        glm = next((r for r in runs if r.get("benchmark_case_id") == case_id and r.get("provider_candidate") == "SILICONFLOW"), None)
        pairs.append(
            {
                "case_id": case_id,
                "title": samples[case_id]["title"],
                "tags": samples[case_id]["tags"],
                "deepseek": _summarize_run(ds),
                "glm": _summarize_run(glm),
            }
        )

    def agg(provider: str) -> dict:
        rows = by_provider.get(provider, [])
        latencies = [float(r["latency_ms"]) for r in rows if r.get("latency_ms")]
        return {
            "n": len(rows),
            "schema_success_rate": aggregate_numeric(rows, "schema_success"),
            "semantic_success_rate": aggregate_numeric(rows, "semantic_success"),
            "http_success_rate": aggregate_numeric(rows, "http_success"),
            "latency_ms_p50": median(latencies),
            "valid_evidence_avg": aggregate_numeric(rows, "valid_evidence"),
            "invalid_quotes_avg": aggregate_numeric(rows, "invalid_quotes"),
            "discarded_claims_avg": aggregate_numeric(rows, "discarded_claims"),
        }

    return {
        "status": "REAL_PROVIDER_BENCHMARK_PASS" if len(runs) >= 8 and pilot_gate_ok(manifest) else "SAMPLED_REAL_PROVIDER_EVALUATION",
        "contract": manifest.get("contract"),
        "git_head": manifest.get("git_head"),
        "spent_cny": manifest.get("spent_cny"),
        "cny_cap": manifest.get("cny_cap"),
        "pair_table": pairs,
        "aggregate": {"DEEPSEEK": agg("DEEPSEEK"), "SILICONFLOW": agg("SILICONFLOW")},
        "recommendation_pending": True,
    }


def _summarize_run(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {
        "status": row.get("status"),
        "error_code": row.get("error_code"),
        "model": row.get("model"),
        "schema_success": row.get("schema_success"),
        "semantic_success": row.get("semantic_success"),
        "latency_ms": row.get("latency_ms"),
        "prompt_tokens": row.get("prompt_tokens"),
        "completion_tokens": row.get("completion_tokens"),
        "valid_evidence": row.get("valid_evidence"),
        "invalid_quotes": row.get("invalid_quotes"),
        "discarded_claims": row.get("discarded_claims"),
        "wall_s": row.get("wall_s"),
    }
