"""Shared Ask turn JSON for API, SSE final events, and tests."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.extraction import ContentChunk, ExtractedDocument
from app.models.retrieval import AskCitation, AskTurn
from app.models.source_item import SourceItem


def build_ask_turn_view(db: Session, turn: AskTurn) -> dict:
    citations = list(db.scalars(select(AskCitation).where(AskCitation.ask_turn_id == turn.id).order_by(AskCitation.citation_number)))
    return {
        "id": str(turn.id),
        "session_id": str(turn.session_id),
        "question": turn.question,
        "status": turn.status,
        "answer_markdown": turn.answer_markdown,
        "provider_type": turn.provider_type,
        "model_name": turn.model_name,
        "excluded_sensitive_source_count": turn.excluded_sensitive_source_count,
        "error_code": turn.error_code,
        "retrieval": (turn.filters_json or {}).get("retrieval"),
        "citations": [_citation_row(db, item) for item in citations],
        "input_tokens": turn.input_tokens,
        "output_tokens": turn.output_tokens,
        "latency_ms": turn.latency_ms,
    }


def build_ask_final_sse_payload(db: Session, turn: AskTurn) -> dict:
    view = build_ask_turn_view(db, turn)
    return {
        "status": view["status"],
        "answer_markdown": view["answer_markdown"],
        "error_code": view["error_code"],
        "citations": view["citations"],
        "provider_type": view["provider_type"],
        "model_name": view["model_name"],
        "usage": {
            "input_tokens": view.get("input_tokens"),
            "output_tokens": view.get("output_tokens"),
            "total_tokens": (
                (view.get("input_tokens") or 0) + (view.get("output_tokens") or 0)
                if view.get("input_tokens") is not None or view.get("output_tokens") is not None
                else None
            ),
        },
    }


def _citation_row(db: Session, item: AskCitation) -> dict:
    chunk = db.get(ContentChunk, item.content_chunk_id)
    source = db.get(SourceItem, item.source_item_id)
    document = None if chunk is None else db.get(ExtractedDocument, chunk.extracted_document_id)
    return {
        "citation_number": item.citation_number,
        "content_chunk_id": str(item.content_chunk_id),
        "source_item_id": str(item.source_item_id),
        "quote_text": item.quote_text,
        "source_title": None if source is None else (source.display_name or "Untitled Source"),
        "heading_path": None if chunk is None else chunk.heading_path,
        "page_number": None if chunk is None else (chunk.metadata_json or {}).get("page_number"),
        "original_url": None if source is None else (source.original_url or source.canonical_url),
        "document_title": None if document is None else document.title,
    }
