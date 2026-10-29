"""Deterministic cover prompt templates (no LLM planner)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.services.image.minimax_contract import (
    DEFAULT_PROMPT_TARGET_CHARS,
    normalize_prompt_text,
    prompt_char_count,
    validate_effective_prompt,
)

PROMPT_VERSION_V1 = "cover-v1"
PROMPT_VERSION = "cover-v6"
GLOBAL_PROMPT_VERSION = "global-cover-r1"
GLOBAL_PROMPT_MAX_CHARS = 800

_DEFAULT_GLOBAL_PROMPT_PATH = Path(__file__).resolve().parents[4] / "prompts" / "cover" / "global-prompt-default-r1.md"
DEFAULT_GLOBAL_PROMPT = _DEFAULT_GLOBAL_PROMPT_PATH.read_text(encoding="utf-8").strip()

PALETTE_DESCRIPTIONS = {
    "cool": "cool cobalt, glacier blue, and blue violet, with crisp soft lighting",
    "neutral": "stone gray, ivory, and restrained natural neutrals, with balanced soft lighting",
    "warm": "muted amber, clay, and russet accents, with soft natural lighting",
    "high_contrast": "high contrast black, white, and one vivid electric accent, with dramatic lighting",
    "low_saturation": "low saturation sage, fog blue, and muted mineral tones, with diffused lighting",
    "vivid": "clear saturated teal, magenta, and vivid complementary accents, with bright lighting",
}

_URL_RE = re.compile(r"https?://\S+")


def _looks_like_url(value: str) -> bool:
    stripped = (value or "").strip().lower()
    return stripped.startswith("http://") or stripped.startswith("https://")


def _compress_topic(text: str, *, max_len: int) -> str:
    cleaned = _URL_RE.sub("", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return ""
    if len(cleaned) <= max_len:
        return cleaned
    cut = cleaned[: max_len - 1].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip("，。,. ") + "…"


def resolve_cover_topic(
    *,
    title: str | None,
    summary: str | None,
    plain_excerpt: str | None,
    source_type: str | None,
) -> tuple[str, bool]:
    """Topic string for the image prompt (never duplicate raw URLs)."""
    title = (title or "").strip()
    summary = (summary or "").strip()
    excerpt = (plain_excerpt or "").strip()
    candidates: list[str] = []
    if title and not _looks_like_url(title):
        candidates.append(title)
    if summary:
        candidates.append(_compress_topic(summary, max_len=200))
    if excerpt:
        candidates.append(_compress_topic(excerpt, max_len=200))
    topic = next((item for item in candidates if len(item) >= 8), "")
    if not topic and title:
        topic = _compress_topic(title, max_len=120)
    if not topic:
        st = (source_type or "资料").upper()
        topic = f"Research topic ({st})"
        return topic, False
    usable = len(topic) >= 12 or (not _looks_like_url(title) and len(title) >= 8)
    return topic[:280], usable


def build_default_cover_prompt(
    *,
    title: str,
    source_type: str | None,
    summary: str | None,
    plain_excerpt: str | None = None,
    color_scheme: str = "auto",
    recent_palettes: list[str] | None = None,
    global_prompt: str | None = None,
    personalization: str | None = None,
) -> tuple[str, bool]:
    topic, usable = resolve_cover_topic(
        title=title,
        summary=summary,
        plain_excerpt=plain_excerpt,
        source_type=source_type,
    )
    palette = choose_palette(topic, color_scheme=color_scheme, recent_palettes=recent_palettes or [])
    style_prompt = normalize_prompt_text(global_prompt or DEFAULT_GLOBAL_PROMPT)
    custom = normalize_prompt_text(personalization or "")
    prompt = compose_cover_prompt(
        global_prompt=style_prompt,
        topic=topic,
        palette=palette,
        personalization=custom,
    )
    return prompt, usable


def compose_cover_prompt(*, global_prompt: str, topic: str, palette: str, personalization: str = "") -> str:
    """Single deterministic composition used by preview and new Cover Runs."""
    global_text = normalize_prompt_text(global_prompt)
    topic_text = normalize_prompt_text(topic)
    custom_text = normalize_prompt_text(personalization)
    if not global_text:
        raise ValueError("COVER_GLOBAL_PROMPT_REQUIRED")
    if len(global_text) > GLOBAL_PROMPT_MAX_CHARS:
        raise ValueError("COVER_GLOBAL_PROMPT_TOO_LONG")
    if len(topic_text) > 360:
        raise ValueError("COVER_TOPIC_TOO_LONG")
    if len(custom_text) > 160:
        raise ValueError("COVER_PERSONALIZATION_TOO_LONG")
    if palette not in PALETTE_DESCRIPTIONS:
        raise ValueError("COVER_PALETTE_INVALID")
    pieces = [global_text, f"Article topic and visual subject: {topic_text}.", f"Palette direction ({palette}): {PALETTE_DESCRIPTIONS[palette]}."]
    if custom_text:
        pieces.append(f"For this image only: {custom_text}")
    result = normalize_prompt_text("\n\n".join(pieces))
    validate_effective_prompt(result, stage="composition")
    return result


def build_cover_prompt(
    *,
    title: str,
    categories: list[str] | None,
    source_type: str | None,
    summary: str | None,
    points: list[str] | None,
    user_prompt: str | None = None,
    plain_excerpt: str | None = None,
    color_scheme: str = "auto",
    recent_palettes: list[str] | None = None,
) -> tuple[str, bool]:
    """Backward-compatible entry: default builder only (no double-wrap of user text)."""
    _ = categories, points, user_prompt
    return build_default_cover_prompt(
        title=title,
        source_type=source_type,
        summary=summary,
        plain_excerpt=plain_excerpt,
        color_scheme=color_scheme,
        recent_palettes=recent_palettes,
    )


def choose_palette(topic: str, *, color_scheme: str = "auto", recent_palettes: list[str] | None = None) -> str:
    scheme = (color_scheme or "auto").strip().lower()
    if scheme != "auto":
        if scheme not in PALETTE_DESCRIPTIONS:
            raise ValueError("COVER_PALETTE_INVALID")
        return scheme
    lowered = topic.lower()
    if any(word in lowered for word in ("medical", "health", "robot", "technology", "software", "ai", "agent", "blockchain", "科技", "医疗", "机器人", "人工智能", "区块链")):
        candidates = ["cool", "high_contrast", "vivid", "neutral"]
    elif any(word in lowered for word in ("finance", "financial", "market", "bank", "investment", "金融", "市场", "投资")):
        candidates = ["cool", "neutral", "high_contrast", "low_saturation"]
    elif any(word in lowered for word in ("nature", "climate", "forest", "agriculture", "自然", "气候", "森林", "农业")):
        candidates = ["low_saturation", "vivid", "neutral", "cool"]
    else:
        candidates = list(PALETTE_DESCRIPTIONS)
    counts = {name: sum(1 for recent in (recent_palettes or [])[-8:] if recent == name) for name in candidates}
    lowest = min(counts.values())
    tied = [name for name in candidates if counts[name] == lowest]
    selector = hashlib.sha256(topic.encode("utf-8")).digest()[0]
    return tied[selector % len(tied)]


def resolve_effective_cover_prompt(*, default_prompt: str, edited_prompt: str | None) -> str:
    """Preview/submit contract: edited body is the full effective prompt sent to MiniMax."""
    edited = (edited_prompt or "").strip()
    if not edited:
        return validate_effective_prompt(default_prompt, stage="default")
    if edited == default_prompt:
        return validate_effective_prompt(default_prompt, stage="default")
    return validate_effective_prompt(edited, stage="user")


def prompt_hash(prompt: str, *, version: str | None = None) -> str:
    version = version or PROMPT_VERSION
    normalized = normalize_prompt_text(prompt)
    return hashlib.sha256(f"{version}\n{normalized}".encode("utf-8")).hexdigest()


def preview_token(prompt: str, *, revision: int, color_scheme: str) -> str:
    body = f"{revision}\n{color_scheme}\n{normalize_prompt_text(prompt)}"
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def default_prompt_within_target(prompt: str) -> bool:
    return prompt_char_count(prompt) <= DEFAULT_PROMPT_TARGET_CHARS
