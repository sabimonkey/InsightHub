import json
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import PROJECT_ROOT

PROMPT_NAME = "source_analysis"
PROMPT_VERSION = "1.1.0"
PROMPT_DIR = PROJECT_ROOT / "prompts" / "source_analysis" / "v1.1.0"
FROZEN_PROMPT_DIR = PROJECT_ROOT / "prompts" / "source_analysis" / "v1"


_FORBID = ConfigDict(extra="forbid")
OUTPUT_MIN = 2000
OUTPUT_STANDARD = 4000
OUTPUT_CEILING = 6000


class EvidenceRef(BaseModel):
    model_config = _FORBID
    chunk_id: str = Field(max_length=64)
    quote: str = Field(max_length=500)


class Statement(BaseModel):
    model_config = _FORBID
    text: str
    confidence: float | None = None
    importance: int | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)


class EvidencedStatement(Statement):
    evidence: list[EvidenceRef] = Field(min_length=1)


class CategoryCandidate(BaseModel):
    model_config = _FORBID
    name: str
    confidence: float | None = None
    reason: str | None = None


class EntityMention(BaseModel):
    model_config = _FORBID
    name: str
    entity_type: str = "OTHER"
    evidence_chunk_ids: list[str] = Field(default_factory=list)


class SourceAnalysis(BaseModel):
    model_config = _FORBID
    summary: str = Field(min_length=1, max_length=400)
    facts: list[EvidencedStatement] = Field(default_factory=list, max_length=8)
    source_claims: list[EvidencedStatement] = Field(default_factory=list, max_length=8)
    inferences: list[Statement] = Field(default_factory=list, max_length=5)
    hypotheses: list[Statement] = Field(default_factory=list, max_length=3)
    unknowns: list[str] = Field(default_factory=list, max_length=5)
    questions: list[str] = Field(default_factory=list, max_length=5)
    category_candidates: list[CategoryCandidate] = Field(default_factory=list, max_length=4)
    topic_candidates: list[str] = Field(default_factory=list, max_length=10)
    entities: list[EntityMention] = Field(default_factory=list, max_length=15)


def load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def _object_schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "additionalProperties": False, "properties": properties, "required": required}


def _evidence_schema(*, required: bool) -> dict:
    schema = {
        "type": "array",
        "items": _object_schema(
            {"chunk_id": {"type": "string", "maxLength": 64}, "quote": {"type": "string", "maxLength": 500}},
            ["chunk_id", "quote"],
        ),
    }
    if required:
        schema["minItems"] = 1
    return schema


def _statement_schema(*, require_evidence: bool) -> dict:
    required = ["text", "evidence"] if require_evidence else ["text"]
    return _object_schema(
        {
            "text": {"type": "string"},
            "confidence": {"type": "number"},
            "importance": {"type": "integer"},
            "evidence": _evidence_schema(required=require_evidence),
        },
        required,
    )


def build_analysis_json_schema() -> dict:
    """Transport schema equivalent to SourceAnalysis. Evidence stays an object array."""
    return _object_schema(
        {
            "summary": {"type": "string", "minLength": 1, "maxLength": 400},
            "facts": {"type": "array", "maxItems": 8, "items": _statement_schema(require_evidence=True)},
            "source_claims": {"type": "array", "maxItems": 8, "items": _statement_schema(require_evidence=True)},
            "inferences": {"type": "array", "maxItems": 5, "items": _statement_schema(require_evidence=False)},
            "hypotheses": {"type": "array", "maxItems": 3, "items": _statement_schema(require_evidence=False)},
            "unknowns": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
            "questions": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
            "category_candidates": {
                "type": "array",
                "maxItems": 4,
                "items": _object_schema(
                    {"name": {"type": "string"}, "confidence": {"type": "number"}, "reason": {"type": "string"}},
                    ["name"],
                ),
            },
            "topic_candidates": {"type": "array", "maxItems": 10, "items": {"type": "string"}},
            "entities": {
                "type": "array",
                "maxItems": 15,
                "items": _object_schema(
                    {
                        "name": {"type": "string"},
                        "entity_type": {"type": "string"},
                        "evidence_chunk_ids": {"type": "array", "items": {"type": "string"}},
                    },
                    ["name"],
                ),
            },
        },
        ["summary", "facts", "source_claims", "inferences", "hypotheses", "unknowns", "questions", "category_candidates", "topic_candidates", "entities"],
    )


def load_schema() -> dict:
    return build_analysis_json_schema()


def analysis_output_budget(*, source_chars: int, chunk_count: int, context_window: int, prompt_chars: int, ceiling: int) -> int:
    from app.services.analysis.budget import analysis_output_budget as _budget

    return _budget(
        source_chars=source_chars,
        chunk_count=chunk_count,
        context_window=context_window,
        prompt_tokens=max(1, prompt_chars // 2),
        ceiling=ceiling,
    )


def repair_output_budget(*, analysis_budget: int, previous_chars: int, context_window: int, prompt_chars: int, ceiling: int) -> int:
    from app.services.analysis.budget import repair_output_budget as _repair

    return _repair(
        analysis_budget=analysis_budget,
        previous_chars=previous_chars,
        context_window=context_window,
        prompt_tokens=max(1, prompt_chars // 2),
        ceiling=ceiling,
    )


def render_user(template: str, **values: str) -> str:
    text = template
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def extract_json_object(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped, flags=re.IGNORECASE).strip()
        if stripped.endswith("```"):
            stripped = stripped[: stripped.rfind("```")].strip()
    start = stripped.find("{")
    if start < 0:
        raise ValueError("no json object")
    fragment = stripped[start:]
    try:
        parsed, _end = json.JSONDecoder().raw_decode(fragment)
    except json.JSONDecodeError:
        end = stripped.rfind("}")
        if end <= start:
            raise ValueError("no json object") from None
        parsed = json.loads(stripped[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("json root must be object")
    return parsed


def sanitize_analysis_payload(data: dict) -> dict:
    """Coerce common model drift without weakening evidence validation in _persist."""
    allowed = set(SourceAnalysis.model_fields.keys())
    cleaned = {key: value for key, value in data.items() if key in allowed}
    if "unknowns_and_questions" in data and not cleaned.get("unknowns") and not cleaned.get("questions"):
        merged = data.get("unknowns_and_questions")
        if isinstance(merged, list):
            cleaned.setdefault("unknowns", [])
            cleaned.setdefault("questions", [])
            for item in merged:
                if isinstance(item, str) and item.strip():
                    cleaned["questions"].append(item.strip())
    summary = cleaned.get("summary")
    if isinstance(summary, str):
        summary = summary.strip()
        if not summary:
            summary = "（无摘要）"
        elif len(summary) > 400:
            summary = summary[:397] + "..."
        cleaned["summary"] = summary
    else:
        cleaned["summary"] = "（无摘要）"
    for key in allowed:
        if key == "summary":
            continue
        if key not in cleaned:
            cleaned[key] = []
    return cleaned


def parse_analysis(text: str) -> SourceAnalysis:
    try:
        return SourceAnalysis.model_validate(sanitize_analysis_payload(extract_json_object(text)))
    except (ValueError, json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(str(exc)[:400]) from exc


def output_language(text: str, configured: str) -> str:
    if configured and configured.lower() != "auto":
        return configured
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    return "中文" if cjk >= 8 else "the source language"
