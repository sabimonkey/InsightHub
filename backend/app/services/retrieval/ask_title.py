"""Deterministic conversation titles from the first user question."""

from __future__ import annotations

import re

_MAX_CHARS = 24
_FILLERS = (
    "请",
    "帮我",
    "能否",
    "可以",
    "一下",
    "麻烦",
    "我想",
    "我想知道",
    "请问",
)


def derive_ask_session_title(question: str) -> str:
    text = " ".join((question or "").split())
    text = text.strip(" ?？!！。，,")
    if not text:
        return "新对话"
    for filler in _FILLERS:
        if text.startswith(filler):
            text = text[len(filler) :].strip()
    text = re.sub(r"[?？!！。]+$", "", text).strip()
    if len(text) <= _MAX_CHARS:
        return text
    cut = text[: _MAX_CHARS + 1]
    for sep in ("，", ",", "、", "；", ";", " "):
        idx = cut.rfind(sep)
        if idx >= 8:
            return cut[:idx].strip()
    return text[:_MAX_CHARS].rstrip() + "…"
