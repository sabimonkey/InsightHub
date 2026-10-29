"""M-PIPELINE-R4: analysis budget and hierarchical merge."""

from __future__ import annotations

import json

from app.core.config import Settings
from app.services.analysis.budget import (
    ProviderLimits,
    analysis_output_budget,
    chunk_groups_budget,
    estimate_tokens,
    merge_payload_char_limit,
    raised_output_budget,
    repair_output_budget,
    resolve_provider_limits,
)


class _Provider:
    provider_type = "SILICONFLOW"
    model = "zai-org/GLM-5.3-Flash"
    context_window = 0
    max_output_tokens = 6000


def test_estimate_tokens_is_conservative_vs_len_div_4():
    text = "a" * 400
    assert estimate_tokens(text) >= len(text) // 4


def test_resolve_provider_limits_uses_glm_pricing_when_window_missing():
    settings = Settings(default_llm_context_window=8000, analysis_max_output_tokens=6000)
    limits = resolve_provider_limits(settings=settings, provider=_Provider(), capabilities={})
    assert limits.context_window >= 1_000_000
    assert limits.output_ceiling == 6000
    assert limits.pricing_source == "zai-org/GLM-5.3-Flash"


def test_analysis_output_budget_respects_context_room():
    budget = analysis_output_budget(
        source_chars=9000,
        chunk_count=30,
        context_window=8000,
        prompt_tokens=7600,
        ceiling=6000,
    )
    assert budget <= 256


def test_raised_output_budget_capped_by_ceiling_and_context():
    retry = raised_output_budget(initial=200, context_window=8000, input_tokens=6000, output_ceiling=6000)
    assert retry <= 6000
    assert retry >= 200


def test_repair_output_budget_scales_with_previous_output():
    repair = repair_output_budget(
        analysis_budget=4000,
        previous_chars=8000,
        context_window=32768,
        prompt_tokens=6000,
        ceiling=6000,
    )
    assert 4000 < repair <= 6000


def test_merge_payload_char_limit_positive():
    assert merge_payload_char_limit(128_000, reserve_output_tokens=4000) >= 2000


def test_chunk_groups_budget():
    assert chunk_groups_budget(8000, 2000) == 8000 - 2000 - 384


def test_compact_merge_does_not_require_source_content_tag():
    from app.services.analysis.service import AnalysisService

    sample = {
        "summary": "x" * 100,
        "facts": [{"text": "fact", "evidence": [{"chunk_id": "c1", "quote": "q" * 300}]}],
        "source_claims": [],
        "inferences": [],
        "unknowns": [],
        "questions": [],
    }
    compact = AnalysisService._compact_intermediate(sample)
    assert len(compact["facts"][0]["evidence"][0]["quote"]) <= 240
    assert json.dumps(compact)
