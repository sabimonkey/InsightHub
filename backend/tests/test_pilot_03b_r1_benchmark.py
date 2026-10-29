"""Harness tests for PILOT-03B-R1 (no live cloud calls)."""

from app.services.benchmark.pilot_03b_r1.constants import CORPUS_CASES, PLANNER_QUERIES, PROVIDER_DEEPSEEK, PROVIDER_GLM
from app.services.benchmark.pilot_03b_r1.corpus import clone_display_name
from app.services.benchmark.pilot_03b_r1.report import build_report, score_analysis


def test_corpus_cases_are_fixed():
    assert len(CORPUS_CASES) >= 6
    assert any(case["case_id"] == "openkb" for case in CORPUS_CASES)


def test_planner_query_expectations():
    assert len(PLANNER_QUERIES) >= 10
    assert PLANNER_QUERIES[2]["expected"] == "COVERAGE"


def test_clone_display_name_isolated():
    assert clone_display_name("openkb").startswith("bench-r1-")


def test_report_routing_is_deterministic_for_fixed_metrics():
    manifest = {
        "routes": [
            {"workflow": "ANALYSIS", "provider_type": PROVIDER_DEEPSEEK},
            {"workflow": "ASK_PLANNER", "provider_type": PROVIDER_GLM},
            {"workflow": "ASK_ANSWER", "provider_type": PROVIDER_DEEPSEEK},
            {"workflow": "BRIEF", "provider_type": PROVIDER_DEEPSEEK},
        ],
        "analysis": [
            {"provider_candidate": PROVIDER_DEEPSEEK, "semantic_success": True, "schema_success": True, "valid_evidence": 5, "claim_count": 5, "attribution_risk_facts": 0, "hallucinated_url_count": 0},
            {"provider_candidate": PROVIDER_GLM, "semantic_success": False, "schema_success": True, "valid_evidence": 1, "claim_count": 5, "attribution_risk_facts": 2, "hallucinated_url_count": 1},
        ],
        "planner": [
            {"provider": PROVIDER_GLM, "mode_correct": True, "parse_success": True, "latency_ms": 1000},
            {"provider": PROVIDER_DEEPSEEK, "mode_correct": False, "parse_success": True, "latency_ms": 2000},
        ],
        "ask_answer": [
            {"provider": PROVIDER_DEEPSEEK, "status": "SUCCEEDED", "validated_citations": 2, "citation_count": 2},
            {"provider": PROVIDER_GLM, "status": "PARTIAL", "validated_citations": 0, "citation_count": 2, "error_code": "NO_VALIDATED_CITATIONS"},
        ],
        "brief": [
            {"provider_candidate": PROVIDER_DEEPSEEK, "status": "PARTIAL", "has_points": True, "dropped_citations": False},
            {"provider_candidate": PROVIDER_GLM, "status": "FAILED", "has_points": False, "dropped_citations": True},
        ],
    }
    report = build_report(manifest)
    assert report["routing_decision"]["ANALYSIS"] == PROVIDER_DEEPSEEK
    assert report["routing_decision"]["ASK_PLANNER"] == PROVIDER_GLM
    assert score_analysis(manifest["analysis"][:1]) > score_analysis(manifest["analysis"][1:])
