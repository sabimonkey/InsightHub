"""User-facing learning-note projection from validated brief synthesis JSON."""

from __future__ import annotations

_STATEMENT_LABELS = {
    "FACT": "关键事实",
    "SOURCE_VIEW": "来源观点",
    "SYNTHESIS": "综合理解",
    "UNCERTAINTY": "待进一步确认",
    "AGREEMENT": "一致看法",
    "DISAGREEMENT": "不同观点",
}


def _label_point(point: dict) -> dict:
    statement = str(point.get("statement_type") or "SYNTHESIS")
    return {
        "text": str(point.get("text") or ""),
        "label": _STATEMENT_LABELS.get(statement, "综合理解"),
        "citations": point.get("citations") or [],
    }


def project_learning_note(payload: dict | None) -> dict | None:
    if not payload or not isinstance(payload, dict):
        return None
    highlights: list[str] = []
    summary = str(payload.get("executive_summary") or "").strip()
    if summary:
        highlights.append(summary)
    for key in ("key_facts", "knowledge_to_remember", "new_developments"):
        for point in payload.get(key) or []:
            text = str(point.get("text") or "").strip()
            if text and len(highlights) < 7:
                highlights.append(text)
    theme_notes = []
    for theme in payload.get("themes") or []:
        points = [_label_point(item) for item in theme.get("points") or []]
        if not points and not theme.get("summary"):
            continue
        theme_notes.append(
            {
                "title": str(theme.get("title") or "主题"),
                "summary": str(theme.get("summary") or ""),
                "points": points,
            }
        )
    sections = {
        "关键事实": [_label_point(item) for item in payload.get("key_facts") or []],
        "来源观点": [_label_point(item) for item in payload.get("agreements") or [] if item],
        "不同观点": [_label_point(item) for item in payload.get("disagreements") or []],
        "综合理解": [_label_point(item) for item in payload.get("knowledge_to_remember") or []],
        "待进一步确认": [_label_point(item) for item in payload.get("open_questions") or []],
    }
    follow_ups = []
    for point in payload.get("open_questions") or []:
        text = str(point.get("text") or "").strip()
        if text:
            follow_ups.append(text)
    return {
        "title": str(payload.get("title") or "学习笔记"),
        "highlights": highlights[:7],
        "theme_notes": theme_notes,
        "sections": {name: rows for name, rows in sections.items() if rows},
        "follow_ups": follow_ups,
    }
