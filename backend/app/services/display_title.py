"""User-facing titles for sources."""

from __future__ import annotations

from urllib.parse import urlsplit

from app.models.source_item import SourceItem


def inbox_list_title(source: SourceItem, *, document_title: str | None = None, analysis_summary: str | None = None, max_len: int = 96) -> str:
    title = resolve_display_title(source, document_title=document_title, analysis_summary=None)
    if len(title) > max_len:
        return title[: max_len - 1] + "…"
    return title


def library_card_title(
    source: SourceItem,
    *,
    document_title: str | None = None,
    analysis_summary: str | None = None,
    max_len: int = 96,
) -> str:
    """Short card title for knowledge grid (no LLM)."""
    title = resolve_display_title(source, document_title=document_title, analysis_summary=analysis_summary)
    if len(title) <= max_len:
        return title
    cut = title[: max_len - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip("，。,. ") + "…"


def resolve_display_title(source: SourceItem, *, document_title: str | None = None, analysis_summary: str | None = None) -> str:
    for candidate in (document_title, source.display_name if source.display_name and not _looks_like_url(source.display_name) else None):
        if candidate and candidate.strip():
            return candidate.strip()
    if analysis_summary and analysis_summary.strip():
        line = analysis_summary.strip().splitlines()[0]
        if len(line) > 120:
            return line[:117] + "…"
        return line
    if source.original_url or source.canonical_url:
        url = source.canonical_url or source.original_url or ""
        host = urlsplit(url).hostname or ""
        if host:
            return f"{host} · {source.source_type}"
    return source.display_name or source.source_type or "未命名资料"


def _looks_like_url(value: str) -> bool:
    stripped = value.strip().lower()
    return stripped.startswith("http://") or stripped.startswith("https://")
