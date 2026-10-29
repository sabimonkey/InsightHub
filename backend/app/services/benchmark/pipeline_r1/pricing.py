"""Conservative USD pricing for budget guard (verify against vendor pages before calls)."""

from __future__ import annotations

from dataclasses import dataclass

# Sources (2026-10-20):
# - DeepSeek API docs: deepseek-v4-pro peak input cache-miss $1.32/M, output $3.96/M
# - SiliconFlow: GLM-5.3-Flash input $0.15/M, output $0.50/M
USD_CNY = 7.25  # conservative FX for cap; actual billing may differ


@dataclass(frozen=True)
class ModelPricing:
    provider_type: str
    model_id: str
    input_usd_per_m: float
    output_usd_per_m: float
    context_tokens: int
    max_output_tokens: int


DEEPSEEK_V4_PRO = ModelPricing(
    provider_type="DEEPSEEK",
    model_id="deepseek-v4-pro",
    input_usd_per_m=1.32,
    output_usd_per_m=3.96,
    context_tokens=1_000_000,
    max_output_tokens=384_000,
)

GLM_53_FLASH = ModelPricing(
    provider_type="SILICONFLOW",
    model_id="zai-org/GLM-5.3-Flash",
    input_usd_per_m=0.15,
    output_usd_per_m=0.50,
    context_tokens=1_049_000,
    max_output_tokens=262_000,
)


def estimate_call_usd(pricing: ModelPricing, *, input_tokens: int, output_tokens: int) -> float:
    return (input_tokens / 1_000_000) * pricing.input_usd_per_m + (output_tokens / 1_000_000) * pricing.output_usd_per_m


def estimate_pair_usd(input_tokens: int, output_tokens: int) -> float:
    return estimate_call_usd(DEEPSEEK_V4_PRO, input_tokens=input_tokens, output_tokens=output_tokens) + estimate_call_usd(
        GLM_53_FLASH, input_tokens=input_tokens, output_tokens=output_tokens
    )


def usd_to_cny(usd: float) -> float:
    return usd * USD_CNY
