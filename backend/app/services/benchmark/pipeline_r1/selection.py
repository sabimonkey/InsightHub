"""Select diverse USER sources for paired benchmark (read-only)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.analysis import AnalysisRun
from app.models.extraction import ContentChunk, ExtractedDocument, ExtractionRun
from app.models.source_item import SourceItem
from app.services.benchmark.pipeline_r1.pricing import estimate_pair_usd, usd_to_cny
from app.services.display_title import resolve_display_title
from app.services.synthesis.service import SynthesisService

USER_SCOPE = "USER"


@dataclass
class SampleCandidate:
    source_id: uuid.UUID
    source_type: str
    title: str
    char_count: int
    est_input_tokens: int
    tags: list[str]
    had_analysis_failure: bool
    language_hint: str


def _body_chars(session: Session, source_id: uuid.UUID) -> int:
    doc = session.scalar(select(ExtractedDocument).where(ExtractedDocument.source_item_id == source_id).order_by(ExtractedDocument.created_at.desc()).limit(1))
    if doc is None:
        return 0
    if doc.plain_text:
        return len(doc.plain_text)
    chunks = list(session.scalars(select(ContentChunk).where(ContentChunk.extracted_document_id == doc.id)))
    return sum(len(c.content or "") for c in chunks)


def _tags(source: SourceItem, chars: int, session: Session, source_id: uuid.UUID) -> list[str]:
    tags: list[str] = []
    url = (source.canonical_url or source.original_url or "").lower()
    if "x.com" in url or "twitter.com" in url:
        tags.append("x_twitter")
    if "github.com" in url:
        tags.append("github")
    if chars > 25_000:
        tags.append("long")
    elif chars < 4_000:
        tags.append("short")
    failed = session.scalar(
        select(AnalysisRun.id).where(AnalysisRun.source_item_id == source_id, AnalysisRun.status == "FAILED").limit(1)
    )
    if failed:
        tags.append("history_failed")
    current = session.scalar(select(AnalysisRun).where(AnalysisRun.source_item_id == source_id, AnalysisRun.is_current.is_(True)))
    if current is None:
        tags.append("never_analyzed")
    elif current.status in {"SUCCEEDED", "PARTIAL"}:
        tags.append("already_analyzed")
    return tags


def _language_hint(text_sample: str) -> str:
    sample = (text_sample or "")[:800]
    cjk = sum(1 for ch in sample if "\u4e00" <= ch <= "\u9fff")
    return "zh" if cjk > 40 else "en"


def list_eligible(session: Session, settings) -> list[SampleCandidate]:
    synthesis = SynthesisService(session, settings)
    rows: list[SampleCandidate] = []
    for source in session.scalars(
        select(SourceItem).where(SourceItem.system_scope == USER_SCOPE, SourceItem.deleted_at.is_(None))
    ):
        if (source.privacy_level or "PRIVATE") == "SENSITIVE":
            continue
        if not synthesis._extraction_ready(source.id)[0]:  # noqa: SLF001
            continue
        chars = _body_chars(session, source.id)
        if chars < 400:
            continue
        doc = session.scalar(select(ExtractedDocument).where(ExtractedDocument.source_item_id == source.id).order_by(ExtractedDocument.created_at.desc()).limit(1))
        sample_text = (doc.plain_text if doc else "")[:800]
        title = resolve_display_title(source, document_title=doc.title if doc else None)
        failed_hist = (
            session.scalar(
                select(AnalysisRun.id).where(AnalysisRun.source_item_id == source.id, AnalysisRun.status == "FAILED").limit(1)
            )
            is not None
        )
        est_in = max(800, chars // 3)
        rows.append(
            SampleCandidate(
                source_id=source.id,
                source_type=source.source_type,
                title=title[:120],
                char_count=chars,
                est_input_tokens=est_in,
                tags=_tags(source, chars, session, source.id),
                had_analysis_failure=failed_hist,
                language_hint=_language_hint(sample_text),
            )
        )
    return rows


def pick_samples(candidates: list[SampleCandidate], limit: int) -> list[SampleCandidate]:
    """Greedy diversity pick."""
    chosen: list[SampleCandidate] = []
    used: set[uuid.UUID] = set()

    def score(row: SampleCandidate) -> tuple:
        novelty = sum(1 for t in row.tags if t not in {t for c in chosen for t in c.tags})
        return (novelty, 1 if "history_failed" in row.tags else 0, row.char_count)

    pool = sorted(candidates, key=score, reverse=True)
    # ensure at least one history_failed if available
    for row in pool:
        if "history_failed" in row.tags and row.source_id not in used:
            chosen.append(row)
            used.add(row.source_id)
            break
    for row in pool:
        if len(chosen) >= limit:
            break
        if row.source_id in used:
            continue
        chosen.append(row)
        used.add(row.source_id)
    return chosen[:limit]


def budget_estimate_cny(samples: list[SampleCandidate], *, output_tokens_per_call: int = 6000, repair_multiplier: float = 1.25) -> dict:
    """Conservative: peak DeepSeek + GLM, optional repair allowance."""
    total_usd = 0.0
    per_sample = []
    for row in samples:
        pair = estimate_pair_usd(row.est_input_tokens, output_tokens_per_call) * repair_multiplier
        total_usd += pair
        per_sample.append({"source_id": str(row.source_id), "est_usd": round(pair, 4), "est_input_tokens": row.est_input_tokens})
    return {
        "assumptions": {
            "output_tokens_per_call": output_tokens_per_call,
            "repair_multiplier": repair_multiplier,
            "pricing": "DeepSeek peak + GLM list (see pipeline_r1/pricing.py)",
            "usd_cny": 7.25,
        },
        "total_est_usd": round(total_usd, 4),
        "total_est_cny": round(usd_to_cny(total_usd), 2),
        "per_sample": per_sample,
    }
