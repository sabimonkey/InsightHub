"""Unified analysis LLM budget estimation (M-PIPELINE-R4)."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.services.analysis.schema import OUTPUT_CEILING, OUTPUT_MIN, OUTPUT_STANDARD
from app.services.benchmark.pipeline_r1.pricing import DEEPSEEK_V4_PRO, GLM_53_FLASH, ModelPricing

# Conservative: over-estimate tokens vs len//4 to avoid context overflow.
_CHARS_PER_TOKEN = 3
_PROTOCOL_OVERHEAD_TOKENS = 384
_RETRY_OUTPUT_FLOOR = 8000
_RETRY_OUTPUT_MULTIPLIER = 3


def estimate_tokens(text: str) -> int:
    if not text:
        return 1
    return max(1, (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)


def lookup_model_pricing(provider_type: str | None, model_id: str | None) -> ModelPricing | None:
    if not model_id:
        return None
    for row in (GLM_53_FLASH, DEEPSEEK_V4_PRO):
        if row.provider_type == provider_type and row.model_id == model_id:
            return row
    return None


@dataclass(frozen=True)
class ProviderLimits:
    context_window: int
    output_ceiling: int
    pricing_source: str | None = None


def resolve_provider_limits(
    *,
    settings: Settings,
    provider,
    capabilities: dict | None = None,
    model_id: str | None = None,
    provider_type: str | None = None,
) -> ProviderLimits:
    caps = capabilities or {}
    pricing = lookup_model_pricing(provider_type or getattr(provider, "provider_type", None), model_id or getattr(provider, "model", None))

    context = int(getattr(provider, "context_window", 0) or 0)
    if not context:
        context = int(caps.get("context_window") or 0)
    if not context and pricing:
        context = pricing.context_tokens
    context = max(settings.default_llm_context_window, context)

    config_ceiling = settings.analysis_max_output_tokens
    deploy_ceiling = caps.get("max_output_tokens") or caps.get("default_max_output_tokens")
    provider_ceiling = getattr(provider, "max_output_tokens", None)
    ceiling_candidates = [config_ceiling]
    if deploy_ceiling:
        ceiling_candidates.append(int(deploy_ceiling))
    if provider_ceiling:
        ceiling_candidates.append(int(provider_ceiling))
    if pricing:
        ceiling_candidates.append(pricing.max_output_tokens)
    output_ceiling = min(ceiling_candidates)
    output_ceiling = max(1, min(output_ceiling, OUTPUT_CEILING))

    return ProviderLimits(
        context_window=context,
        output_ceiling=output_ceiling,
        pricing_source=pricing.model_id if pricing else None,
    )


def analysis_output_budget(
    *,
    source_chars: int,
    chunk_count: int,
    context_window: int,
    prompt_tokens: int,
    ceiling: int,
) -> int:
    if source_chars <= 1200 and chunk_count <= 3:
        target = OUTPUT_MIN
    elif source_chars <= 8000 and chunk_count <= 24:
        target = OUTPUT_STANDARD
    else:
        target = OUTPUT_CEILING
    target = min(target, OUTPUT_CEILING, max(1, ceiling))
    room = context_window - max(1, prompt_tokens) - _PROTOCOL_OVERHEAD_TOKENS
    if room >= 256:
        target = min(target, max(256, room - 64))
    elif room > 0:
        target = min(target, max(1, room))
    else:
        target = min(target, max(1, ceiling))
    return max(1, target)


def repair_output_budget(
    *,
    analysis_budget: int,
    previous_chars: int,
    context_window: int,
    prompt_tokens: int,
    ceiling: int,
) -> int:
    previous_tokens = estimate_tokens("x" * max(1, previous_chars))
    target = min(OUTPUT_CEILING, max(analysis_budget, previous_tokens + 1500), max(1, ceiling))
    room = context_window - max(1, prompt_tokens) - _PROTOCOL_OVERHEAD_TOKENS
    if room >= 256:
        target = min(target, max(256, room - 64))
    return max(1, target)


def chunk_groups_budget(context_window: int, output_reserve: int, *, overhead_tokens: int = _PROTOCOL_OVERHEAD_TOKENS) -> int:
    budget = context_window - output_reserve - overhead_tokens
    return max(0, budget)


def raised_output_budget(
    *,
    initial: int,
    context_window: int,
    input_tokens: int,
    output_ceiling: int,
) -> int:
    # One bounded stretch for finish_reason=length when the configured ceiling is artificially low.
    stretch_cap = min(output_ceiling, OUTPUT_CEILING)
    target = min(stretch_cap, max(_RETRY_OUTPUT_FLOOR, initial * _RETRY_OUTPUT_MULTIPLIER))
    room = context_window - max(1, input_tokens) - _PROTOCOL_OVERHEAD_TOKENS
    if room < 256:
        return max(1, min(initial, target))
    return max(1, min(target, room - 64))


def merge_payload_char_limit(context_window: int, *, reserve_output_tokens: int) -> int:
    """Character budget for hierarchical merge user message (intermediate JSON only)."""
    input_tokens = context_window - reserve_output_tokens - _PROTOCOL_OVERHEAD_TOKENS
    return max(2000, min(24_000, input_tokens * _CHARS_PER_TOKEN))
