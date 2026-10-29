"""Aggregate benchmark metrics and routing recommendation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.benchmark.pilot_03b_r1.constants import PROVIDER_DEEPSEEK, PROVIDER_GLM


def _group(rows: list[dict], provider_key: str = "provider") -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        key = row.get(provider_key) or row.get("provider_candidate")
        if not key:
            continue
        grouped.setdefault(str(key), []).append(row)
    return grouped


def _rate(rows: list[dict], key) -> float:
    if not rows:
        return 0.0
    if callable(key):
        return sum(1 for row in rows if key(row)) / len(rows)
    return sum(1 for row in rows if row.get(key)) / len(rows)


def _avg(rows: list[dict], key: str) -> float | None:
    values = [row[key] for row in rows if row.get(key) is not None]
    if not values:
        return None
    return sum(values) / len(values)


def score_analysis(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    grounding = _rate(rows, "semantic_success") * 30
    citations = min(1.0, (_avg(rows, "valid_evidence") or 0) / max(1.0, _avg(rows, "claim_count") or 1)) * 30
    stability = _rate(rows, "schema_success") * 15
    attribution_penalty = min(10.0, (_avg(rows, "attribution_risk_facts") or 0) * 2)
    hallucination_penalty = min(20.0, (_avg(rows, "hallucinated_url_count") or 0) * 10)
    return max(0.0, grounding + citations + stability - attribution_penalty - hallucination_penalty)


def score_planner(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    return _rate(rows, "mode_correct") * 70 + _rate(rows, "parse_success") * 20 + (10 if (_avg(rows, "latency_ms") or 99999) < 8000 else 0)


def score_ask(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    citation_rate = (_avg(rows, "validated_citations") or 0) / max(1.0, _avg(rows, "citation_count") or 1)
    success = _rate(rows, lambda r: r.get("status") == "SUCCEEDED")
    no_valid = 1.0 - _rate(rows, lambda r: r.get("error_code") == "NO_VALIDATED_CITATIONS")
    return citation_rate * 45 + success * 35 + no_valid * 20


def score_brief(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    success = sum(1 for row in rows if row.get("status") in {"SUCCEEDED", "PARTIAL"}) / len(rows)
    points = _rate(rows, "has_points") * 50
    dropped_penalty = _rate(rows, "dropped_citations") * 10
    return success * 30 + points - dropped_penalty


def decide(workflow: str, deepseek: float, glm: float, deepseek_rows: list[dict], glm_rows: list[dict]) -> tuple[str, str]:
    gap = deepseek - glm
    if abs(gap) < 5:
        if workflow == "ASK_PLANNER":
            return (
                PROVIDER_GLM,
                f"{workflow}: scores within 5% (DeepSeek={deepseek:.1f}, GLM={glm:.1f}); retained GLM planner (R0 default, no parse-quality edge).",
            )
        deep_latency = _avg(deepseek_rows, "latency_ms") or 0
        glm_latency = _avg(glm_rows, "latency_ms") or 0
        winner = PROVIDER_DEEPSEEK if deep_latency <= glm_latency else PROVIDER_GLM
        reason = f"{workflow}: scores within 5% (DeepSeek={deepseek:.1f}, GLM={glm:.1f}); picked lower latency."
        return winner, reason
    if gap >= 5:
        return PROVIDER_DEEPSEEK, f"{workflow}: DeepSeek higher score ({deepseek:.1f} vs {glm:.1f})."
    return PROVIDER_GLM, f"{workflow}: GLM higher score ({glm:.1f} vs {deepseek:.1f})."


def build_report(manifest: dict) -> dict[str, Any]:
    analysis = _group(manifest.get("analysis") or [], "provider_candidate")
    planner = _group(manifest.get("planner") or [])
    ask = _group(manifest.get("ask_answer") or [])
    brief = _group(manifest.get("brief") or [], "provider_candidate")

    a_ds = score_analysis(analysis.get(PROVIDER_DEEPSEEK, []))
    a_glm = score_analysis(analysis.get(PROVIDER_GLM, []))
    p_ds = score_planner(planner.get(PROVIDER_DEEPSEEK, []))
    p_glm = score_planner(planner.get(PROVIDER_GLM, []))
    q_ds = score_ask(ask.get(PROVIDER_DEEPSEEK, []))
    q_glm = score_ask(ask.get(PROVIDER_GLM, []))
    b_ds = score_brief(brief.get(PROVIDER_DEEPSEEK, []))
    b_glm = score_brief(brief.get(PROVIDER_GLM, []))

    analysis_pick, analysis_reason = decide("ANALYSIS", a_ds, a_glm, analysis.get(PROVIDER_DEEPSEEK, []), analysis.get(PROVIDER_GLM, []))
    planner_pick, planner_reason = decide("ASK_PLANNER", p_ds, p_glm, planner.get(PROVIDER_DEEPSEEK, []), planner.get(PROVIDER_GLM, []))
    answer_pick, answer_reason = decide("ASK_ANSWER", q_ds, q_glm, ask.get(PROVIDER_DEEPSEEK, []), ask.get(PROVIDER_GLM, []))
    brief_pick, brief_reason = decide("BRIEF", b_ds, b_glm, brief.get(PROVIDER_DEEPSEEK, []), brief.get(PROVIDER_GLM, []))

    current = {row["workflow"]: row for row in manifest.get("routes") or []}
    proposed = {
        "ANALYSIS": analysis_pick,
        "ASK_PLANNER": planner_pick,
        "ASK_ANSWER": answer_pick,
        "BRIEF": brief_pick,
    }
    changes = {key: {"before": current.get(key, {}).get("provider_type"), "after": value} for key, value in proposed.items() if current.get(key, {}).get("provider_type") != value}

    return {
        "scores": {
            "analysis": {PROVIDER_DEEPSEEK: round(a_ds, 2), PROVIDER_GLM: round(a_glm, 2)},
            "planner": {PROVIDER_DEEPSEEK: round(p_ds, 2), PROVIDER_GLM: round(p_glm, 2)},
            "ask_answer": {PROVIDER_DEEPSEEK: round(q_ds, 2), PROVIDER_GLM: round(q_glm, 2)},
            "brief": {PROVIDER_DEEPSEEK: round(b_ds, 2), PROVIDER_GLM: round(b_glm, 2)},
        },
        "routing_decision": proposed,
        "routing_reasons": {
            "ANALYSIS": analysis_reason,
            "ASK_PLANNER": planner_reason,
            "ASK_ANSWER": answer_reason,
            "BRIEF": brief_reason,
        },
        "route_changes": changes or {"status": "NO_CHANGE"},
    }


def write_report(root: Path, manifest: dict, report: dict) -> None:
    final = root / "manifest.json"
    tmp = root / "manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(final)
    stale_partial = root / "manifest.partial.json"
    if stale_partial.exists():
        stale_partial.unlink()
    (root / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# InsightHub PILOT-03B-R1 Benchmark Summary",
        "",
        f"- commit: {manifest.get('commit')}",
        f"- started: {manifest.get('started_at')}",
        f"- finished: {manifest.get('finished_at')}",
        "",
        "## Routing decision",
    ]
    for workflow, provider in (report.get("routing_decision") or {}).items():
        lines.append(f"- {workflow}: {provider}")
        lines.append(f"  - {report.get('routing_reasons', {}).get(workflow)}")
    lines.append("")
    lines.append("## Scores")
    lines.append(json.dumps(report.get("scores"), ensure_ascii=False, indent=2))
    (root / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
