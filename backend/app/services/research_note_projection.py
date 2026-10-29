"""Research Note reading projection — presentation only, not a knowledge layer."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

SOURCE_TYPE_LABELS = {
    "URL": "网页",
    "TEXT": "文本",
    "FILE": "文件",
    "PDF": "PDF",
    "DOCX": "文件",
    "IMAGE": "图片",
}

_ATTRIBUTION_MARKERS = (
    "帖子介绍称",
    "作者认为",
    "作者表示",
    "来源称",
    "文中指出",
    "该文提到",
    "文章称",
    "报道称",
    "介绍称",
    "网页介绍称",
)

_LOW_VALUE_HYPOTHESIS_HINTS = ("可能很受欢迎", "未来可能很", "或许会大火", "说不定会")

_META_NOISE_RE = re.compile(
    r"(浏览量|点赞|转发|回复数|impressions?|views?|likes?|retweets?|"
    r"发布了?一?条?(帖子|推文|微博)|发帖时间|作者发布|声称列出|"
    r"谷歌不想|google doesn't want|follow me|关注账号)",
    re.IGNORECASE,
)

_GENERIC_QUESTION_RE = re.compile(
    r"^(是否|会不会|能否|有没有|为什么|怎么|如何|这些网站|该网站|作者是否|谷歌是否).{0,48}[？?]$"
)

_URL_RE = re.compile(r"https?://[^\s)\]>,\"']+")

_TYPE_RANK = {"FACT": 0, "SOURCE_CLAIM": 1, "INFERENCE": 2, "HYPOTHESIS": 3}


@dataclass(frozen=True)
class _ClaimView:
    id: uuid.UUID
    claim_type: str
    text: str
    importance: int | None
    sequence: int


def _norm_key(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip().lower())


def _near_duplicate(a: str, b: str) -> bool:
    ka, kb = _norm_key(a), _norm_key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    shorter, longer = (ka, kb) if len(ka) <= len(kb) else (kb, ka)
    if shorter in longer and len(shorter) / len(longer) >= 0.82:
        return True
    return False


def _already_attributed(text: str) -> bool:
    head = text.strip()[:24]
    return any(head.startswith(marker) for marker in _ATTRIBUTION_MARKERS) or "认为" in head[:18]


def attribution_prefix(source_type: str | None) -> str:
    if source_type in {"URL", "WEB"}:
        return "网页介绍称，"
    return "帖子介绍称，"


def present_source_claim(text: str, source_type: str | None = None) -> str:
    stripped = (text or "").strip()
    if not stripped:
        return stripped
    if _already_attributed(stripped):
        return stripped
    prefix = attribution_prefix(source_type)
    if stripped.startswith(prefix.rstrip("，")):
        return stripped
    return f"{prefix}{stripped.rstrip('。')}。"


def present_claim_text(claim_type: str, text: str, source_type: str | None = None) -> str:
    if claim_type == "SOURCE_CLAIM":
        return present_source_claim(text, source_type)
    return (text or "").strip()


def _low_value_hypothesis(text: str) -> bool:
    return any(hint in text for hint in _LOW_VALUE_HYPOTHESIS_HINTS) and len(text) < 96


def _is_meta_noise(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return True
    if _META_NOISE_RE.search(stripped) and len(stripped) < 160:
        return True
    if stripped.startswith("作者") and ("发布" in stripped or "账号" in stripped) and len(stripped) < 120:
        return True
    return False


def _claim_sort_key(claim: _ClaimView) -> tuple:
    imp = claim.importance if claim.importance is not None else 0
    return (-imp, _TYPE_RANK.get(claim.claim_type, 9), claim.sequence)


def _summary_paragraphs(summary: str | None) -> list[str]:
    if not summary or not summary.strip():
        return []
    text = summary.strip()
    parts = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    if not parts:
        parts = [text]
    out: list[str] = []
    for part in parts:
        if _is_meta_noise(part):
            continue
        out.append(part)
        if len(out) >= 2:
            break
    if not out and text and not _is_meta_noise(text):
        out = [text]
    return out


def _dedupe_points(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        if not line:
            continue
        if any(_near_duplicate(line, kept) for kept in out):
            continue
        out.append(line)
    return out


def _resource_items(views: list[_ClaimView], source_type: str | None, *, skip_keys: list[str]) -> list[dict]:
    items: list[dict] = []
    seen: list[str] = []
    for claim in sorted(views, key=_claim_sort_key):
        if claim.claim_type not in {"FACT", "SOURCE_CLAIM"}:
            continue
        raw = (claim.text or "").strip()
        if not raw or _is_meta_noise(raw):
            continue
        if any(_near_duplicate(raw, key) for key in skip_keys):
            continue
        urls = _URL_RE.findall(raw)
        has_resource_hint = bool(urls) or ".com" in raw.lower() or "网站" in raw or "工具" in raw
        if not has_resource_hint and len(raw) > 120:
            has_resource_hint = True
        if not has_resource_hint:
            continue
        line = present_claim_text(claim.claim_type, raw, source_type)
        if any(_near_duplicate(line, s) for s in seen):
            continue
        items.append({"text": line, "url": urls[0] if urls else None})
        seen.append(line)
        if len(items) >= 36:
            break
    return items


def _important_reminders(views: list[_ClaimView], source_type: str | None) -> list[str]:
    reminders: list[str] = []
    for claim in views:
        if claim.claim_type not in {"UNKNOWN", "HYPOTHESIS", "INFERENCE"}:
            continue
        text = (claim.text or "").strip()
        if not text or len(text) < 12:
            continue
        if claim.claim_type in {"UNKNOWN", "HYPOTHESIS"} and _GENERIC_QUESTION_RE.match(text):
            continue
        if claim.claim_type == "HYPOTHESIS" and _low_value_hypothesis(text):
            continue
        if claim.claim_type == "INFERENCE" and (claim.importance or 0) < 2:
            continue
        limit_markers = ("登录", "验证", "未验证", "无法确认", "限制", "风险", "版权", "不完整", "缺少")
        if claim.claim_type == "UNKNOWN" and not any(m in text for m in limit_markers):
            continue
        line = present_claim_text(claim.claim_type, text, source_type)
        if any(_near_duplicate(line, r) for r in reminders):
            continue
        reminders.append(line)
        if len(reminders) >= 4:
            break
    return reminders


def project_research_note_reading(
    *,
    summary: str | None,
    claims: list[Any],
    evidence_by_claim: dict[uuid.UUID, list[Any]],
    source_type: str | None,
    source_type_label: str | None,
    author: str | None,
    collected_at: str | None,
    original_url: str | None,
    canonical_url: str | None,
) -> dict:
    views = [
        _ClaimView(
            id=claim.id,
            claim_type=claim.claim_type,
            text=claim.text,
            importance=claim.importance,
            sequence=claim.sequence,
        )
        for claim in claims
    ]
    core_summary_paragraphs = _summary_paragraphs(summary)
    summary_keys = list(core_summary_paragraphs)

    resource_items = _resource_items(views, source_type, skip_keys=summary_keys)
    resource_text_keys = [item["text"] for item in resource_items]

    point_candidates: list[_ClaimView] = [c for c in views if c.claim_type in {"FACT", "SOURCE_CLAIM"}]
    point_candidates.extend([c for c in views if c.claim_type == "INFERENCE" and (c.importance or 0) >= 2])
    point_candidates.sort(key=_claim_sort_key)
    core_points: list[str] = []
    seen_bodies: list[str] = []
    for claim in point_candidates:
        if _is_meta_noise(claim.text):
            continue
        if any(_near_duplicate(claim.text, prior) for prior in seen_bodies):
            continue
        line = present_claim_text(claim.claim_type, claim.text, source_type)
        if not line:
            continue
        if any(_near_duplicate(line, p) for p in core_points):
            continue
        if any(_near_duplicate(line, rt) for rt in resource_text_keys):
            continue
        if any(_near_duplicate(line, sk) for sk in summary_keys):
            continue
        core_points.append(line)
        seen_bodies.append(claim.text)
        if len(core_points) >= 8:
            break
    core_points = _dedupe_points(core_points)

    important_reminders = _important_reminders(views, source_type)

    evidence_items: list[dict] = []
    verified = 0
    for claim in views:
        ev_rows = evidence_by_claim.get(claim.id, [])
        if not ev_rows:
            continue
        verified += len(ev_rows)
        quotes = [{"text": (ev.quote_text or "").strip(), "source_label": source_type_label or "原始资料"} for ev in ev_rows if (ev.quote_text or "").strip()]
        if not quotes:
            continue
        evidence_items.append(
            {
                "conclusion": present_claim_text(claim.claim_type, claim.text, source_type),
                "quotes": quotes,
            }
        )

    url = original_url or canonical_url
    core_content = None
    if resource_items:
        title = "资源清单" if len(resource_items) >= 3 else "核心内容"
        core_content = {"title": title, "items": resource_items}

    return {
        "core_summary": {"paragraphs": core_summary_paragraphs} if core_summary_paragraphs else None,
        "core_content": core_content,
        "core_points": core_points,
        "important_reminders": important_reminders or None,
        "inferences_and_open": None,
        "source_and_evidence": {
            "source_type_label": source_type_label or SOURCE_TYPE_LABELS.get(source_type or "", source_type or "资料"),
            "author": author,
            "collected_at": collected_at,
            "original_url": url,
            "evidence_summary": {
                "verified_count": verified,
                "items": evidence_items,
            },
        },
    }


def reading_has_body(reading: dict | None) -> bool:
    if not reading:
        return False
    summary = reading.get("core_summary") or {}
    if summary.get("paragraphs"):
        return True
    content = reading.get("core_content") or {}
    if content.get("items"):
        return True
    return bool(reading.get("core_points"))


def research_note_markdown_from_note(note: dict) -> str:
    reading = note.get("reading") or {}
    title = note.get("title") or "资料摘要"
    lines = [f"# {title}", ""]
    meta_bits: list[str] = []
    src = reading.get("source_and_evidence") or {}
    if src.get("source_type_label"):
        meta_bits.append(str(src["source_type_label"]))
    if note.get("collected_at"):
        try:
            from datetime import datetime

            dt = datetime.fromisoformat(note["collected_at"].replace("Z", "+00:00"))
            meta_bits.append(f"收藏于 {dt.date().isoformat()}")
        except ValueError:
            meta_bits.append(f"收藏于 {note['collected_at']}")
    if meta_bits:
        lines.append(f"> 来源：{' · '.join(meta_bits)}")
        lines.append("")

    summary = reading.get("core_summary") or {}
    paragraphs = summary.get("paragraphs") or []
    if paragraphs:
        lines.extend(["## 核心摘要", ""])
        for para in paragraphs:
            lines.append(para)
            lines.append("")

    content = reading.get("core_content") or {}
    content_items = content.get("items") or []
    if content_items:
        heading = content.get("title") or "核心内容"
        lines.extend([f"## {heading}", ""])
        for item in content_items:
            url = item.get("url")
            text = item.get("text") or ""
            if url:
                lines.append(f"- [{text}]({url})")
            else:
                lines.append(f"- {text}")
        lines.append("")

    points = reading.get("core_points") or []
    if points:
        lines.extend(["## 核心要点", ""])
        for item in points:
            lines.append(f"- {item}")
        lines.append("")

    reminders = reading.get("important_reminders") or []
    if reminders:
        lines.extend(["## 重要提醒", ""])
        for item in reminders:
            lines.append(f"- {item}")
        lines.append("")

    if src:
        lines.extend(["## 来源与依据", ""])
        if src.get("source_type_label") or src.get("author"):
            label = src.get("source_type_label") or ""
            author = src.get("author")
            if author:
                lines.append(f"原始资料：{label} · {author}" if label else f"原始资料：{author}")
            elif label:
                lines.append(f"原始资料：{label}")
        if src.get("original_url"):
            lines.append(f"原文：{src['original_url']}")
        lines.append("")

    analysis = note.get("analysis") or {}
    provider = analysis.get("provider")
    model = analysis.get("model_name")
    prompt = analysis.get("prompt_version")
    if provider or model or prompt:
        lines.extend(["---", ""])
        trail = []
        if provider and model:
            trail.append(f"{provider} / {model}")
        elif provider or model:
            trail.append(provider or model)
        if prompt:
            trail.append(f"source_analysis {prompt}" if analysis.get("prompt_name") == "source_analysis" else str(prompt))
        if trail:
            lines.append(f"AI 分析：{' · '.join(trail)}")
    return "\n".join(lines).strip() + "\n"
