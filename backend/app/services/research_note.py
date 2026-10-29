"""Research Note presentation projection (not a new knowledge layer)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.analysis import AnalysisResult, AnalysisRun, Claim, Evidence
from app.models.extraction import ExtractedDocument
from app.models.ingestion_record import IngestionRecord
from app.models.organization import Category, Entity, EntityMention, SourceCategoryAssignment, SourceTopicAssignment, Topic
from app.models.source_item import SourceItem
from app.services.analysis.service import AnalysisService
from app.services.display_title import resolve_display_title
from app.services.llm.routing import resolve_workflow
from app.services.analysis.stages import read_stage, stage_label
from app.services.research_note_projection import (
    SOURCE_TYPE_LABELS,
    project_research_note_reading,
    reading_has_body,
    research_note_markdown_from_note,
)

CLAIM_GROUPS = {
    "FACT": "关键事实",
    "SOURCE_CLAIM": "来源观点",
    "INFERENCE": "推断",
    "HYPOTHESIS": "待验证",
    "UNKNOWN": "信息不足",
}

ANALYSIS_STATUS_LABELS = {
    "SUCCEEDED": "已完成",
    "PARTIAL": "部分完成",
    "FAILED": "失败",
    "RUNNING": "分析中",
    "PENDING": "等待中",
    "QUEUED": "等待中",
}

_FAILED_USER_MESSAGES = {
    "STRUCTURED_OUTPUT_INVALID": "模型输出未能通过结构化校验，请重试或更换模型。",
    "EVIDENCE_VALIDATION_FAILED": "模型输出中的部分证据无法核对，未生成可用摘要。",
    "PROVIDER_UNAVAILABLE": "分析服务暂时不可用，请稍后重试。",
    "WORKER_NOT_CONSUMING": "后台分析任务尚未开始，请确认 Worker 已启动后重试。",
}


def _latest_run(session: Session, source_id: uuid.UUID) -> AnalysisRun | None:
    return session.scalar(
        select(AnalysisRun).where(AnalysisRun.source_item_id == source_id).order_by(AnalysisRun.created_at.desc()).limit(1)
    )


def _content_run(session: Session, source_id: uuid.UUID) -> AnalysisRun | None:
    source = session.get(SourceItem, source_id)
    stmt = select(AnalysisRun).where(
        AnalysisRun.source_item_id == source_id,
        AnalysisRun.status.in_(("SUCCEEDED", "PARTIAL")),
    )
    if source is not None and source.system_scope == "USER":
        stmt = stmt.where(AnalysisRun.provider_type != "FAKE", AnalysisRun.model_name != "fake-model")
    return session.scalar(stmt.order_by(AnalysisRun.is_current.desc(), AnalysisRun.created_at.desc()).limit(1))


def content_analysis_summary(session: Session, source_id: uuid.UUID) -> str | None:
    run = _content_run(session, source_id)
    if run is None:
        return None
    result = session.scalar(select(AnalysisResult).where(AnalysisResult.analysis_run_id == run.id))
    return result.summary if result else None


def analysis_status_for_source(session: Session, source_id: uuid.UUID) -> tuple[str, str | None]:
    latest = _latest_run(session, source_id)
    if latest is None:
        return "未分析", None
    source = session.get(SourceItem, source_id)
    if source is not None and source.system_scope == "USER" and (latest.provider_type == "FAKE" or latest.model_name == "fake-model"):
        trusted = _content_run(session, source_id)
        if trusted is None:
            return "需要真实模型重新分析", "FAKE_RESULT_UNTRUSTED"
        return f"{ANALYSIS_STATUS_LABELS.get(trusted.status, trusted.status)}（已忽略当前模拟结果）", "FAKE_CURRENT_IGNORED"
    if latest.status in {"RUNNING", "PENDING", "QUEUED"}:
        from app.services.maintenance.system import worker_detected

        if latest.status in {"PENDING", "QUEUED"} and not worker_detected():
            return "等待 Worker", "WORKER_NOT_CONSUMING"
        return ANALYSIS_STATUS_LABELS.get(latest.status, latest.status), latest.status
    content = _content_run(session, source_id)
    if latest.status == "FAILED":
        if content is not None:
            return ANALYSIS_STATUS_LABELS.get(content.status, content.status), content.status
        return "分析失败", "FAILED"
    if latest.is_current:
        return ANALYSIS_STATUS_LABELS.get(latest.status, latest.status), latest.status
    if content is not None:
        return ANALYSIS_STATUS_LABELS.get(content.status, content.status), content.status
    return ANALYSIS_STATUS_LABELS.get(latest.status, latest.status), latest.status


def build_research_note(session: Session, source_id: uuid.UUID, settings: Settings) -> dict:
    source = session.get(SourceItem, source_id)
    if source is None:
        raise LookupError("SOURCE_NOT_FOUND")
    doc = session.scalar(select(ExtractedDocument).where(ExtractedDocument.source_item_id == source_id).order_by(ExtractedDocument.created_at.desc()))
    service = AnalysisService(session, inline=True, settings=settings)
    latest_run = _latest_run(session, source_id)
    content_run = _content_run(session, source_id)
    view_run_id = content_run.id if content_run is not None else (latest_run.id if latest_run is not None else None)
    run, result, claims, evidence, history, configured = service.view(source_id, view_run_id)
    if source.system_scope == "USER" and run is not None and (run.provider_type == "FAKE" or run.model_name == "fake-model"):
        result, claims, evidence = None, [], []
    status_label, status_code = analysis_status_for_source(session, source_id)
    analysis_failure = None
    if latest_run is not None and latest_run.status == "FAILED":
        message = _FAILED_USER_MESSAGES.get(latest_run.error_code or "", latest_run.error_message or "分析失败")
        analysis_failure = {
            "error_code": latest_run.error_code,
            "error_message": latest_run.error_message,
            "user_message": message,
            "run_id": str(latest_run.id),
            "supersedes_content": content_run is not None and content_run.id != latest_run.id,
        }
    summary = result.summary if result else None
    title = resolve_display_title(source, document_title=doc.title if doc else None, analysis_summary=summary)
    by_claim: dict[uuid.UUID, list[Evidence]] = {}
    for item in evidence:
        by_claim.setdefault(item.claim_id, []).append(item)
    grouped: dict[str, list[dict]] = {}
    highlights: list[dict] = []
    for claim in claims:
        payload = {
            "id": str(claim.id),
            "claim_type": claim.claim_type,
            "label": CLAIM_GROUPS.get(claim.claim_type, claim.claim_type),
            "text": claim.text,
            "evidence": [
                {
                    "id": str(item.id),
                    "content_chunk_id": str(item.content_chunk_id),
                    "quote_text": item.quote_text,
                    "page_number": item.page_number,
                }
                for item in by_claim.get(claim.id, [])
            ],
        }
        grouped.setdefault(claim.claim_type, []).append(payload)
        if len(highlights) < 6 and claim.claim_type in {"FACT", "SOURCE_CLAIM", "INFERENCE"}:
            highlights.append({"text": claim.text, "claim_type": claim.claim_type, "label": payload["label"]})
    categories = []
    for row in session.scalars(select(SourceCategoryAssignment).where(SourceCategoryAssignment.source_item_id == source_id, SourceCategoryAssignment.status == "ACTIVE")):
        if source.system_scope == "USER" and row.origin != "USER" and row.analysis_run_id is not None:
            origin_run = session.get(AnalysisRun, row.analysis_run_id)
            if origin_run is not None and (origin_run.provider_type == "FAKE" or origin_run.model_name == "fake-model"):
                continue
        cat = session.get(Category, row.category_id)
        if cat:
            categories.append({"slug": cat.slug, "name": cat.name})
    topics = []
    for row in session.scalars(select(SourceTopicAssignment).where(SourceTopicAssignment.source_item_id == source_id, SourceTopicAssignment.status == "ACTIVE")):
        if source.system_scope == "USER" and row.origin != "USER" and row.analysis_run_id is not None:
            origin_run = session.get(AnalysisRun, row.analysis_run_id)
            if origin_run is not None and (origin_run.provider_type == "FAKE" or origin_run.model_name == "fake-model"):
                continue
        topic = session.get(Topic, row.topic_id)
        if topic:
            topics.append({"id": str(topic.id), "name": topic.name})
    entities = []
    author = None
    for row in session.scalars(select(EntityMention).where(EntityMention.source_item_id == source_id).limit(12)):
        if source.system_scope == "USER":
            origin_run = session.get(AnalysisRun, row.analysis_run_id)
            if origin_run is not None and (origin_run.provider_type == "FAKE" or origin_run.model_name == "fake-model"):
                continue
        ent = session.get(Entity, row.entity_id)
        entities.append({"name": row.mention_text, "entity_type": ent.entity_type if ent else "ENTITY"})
        if author is None and ent and ent.entity_type == "PERSON":
            author = row.mention_text
    collected = session.scalar(
        select(IngestionRecord.collected_at)
        .where(IngestionRecord.source_item_id == source_id, IngestionRecord.origin == "USER_COLLECTION")
        .order_by(IngestionRecord.collected_at.asc())
        .limit(1)
    )
    ask_route = None
    try:
        spec = resolve_workflow(session, settings, "ASK_ANSWER", None)
        ask_route = (spec.deployment_display_name or spec.model) if spec.is_local else spec.name
    except Exception:
        ask_route = None
    analysis_meta = None
    meta_run = content_run if content_run is not None else latest_run
    if meta_run is not None:
        provider_label = {
            "DEEPSEEK": "DeepSeek",
            "SILICONFLOW": "SiliconFlow",
            "LOCAL_OPENAI_COMPATIBLE": "LM Studio",
            "GENERIC_OPENAI_COMPATIBLE": "Generic",
            "FAKE": "Fake",
        }.get(meta_run.provider_type or "", meta_run.provider_type or "—")
        analysis_meta = {
            "run_id": str(meta_run.id),
            "status": meta_run.status,
            "provider": provider_label,
            "provider_type": meta_run.provider_type,
            "model_name": meta_run.model_name,
            "is_simulated": meta_run.provider_type == "FAKE" or meta_run.model_name == "fake-model",
            "untrusted_for_user_research": source.system_scope == "USER" and (meta_run.provider_type == "FAKE" or meta_run.model_name == "fake-model"),
            "current_run_is_simulated": bool(latest_run and (latest_run.provider_type == "FAKE" or latest_run.model_name == "fake-model")),
            "prompt_name": meta_run.prompt_name,
            "prompt_version": meta_run.prompt_version,
            "is_cloud": (meta_run.provider_type or "") not in {"LOCAL_OPENAI_COMPATIBLE", "FAKE"},
            "completed_at": meta_run.completed_at.isoformat() if meta_run.completed_at else None,
            "latency_ms": meta_run.latency_ms,
            "total_tokens": meta_run.total_tokens,
        }
    collected_iso = collected.isoformat() if isinstance(collected, datetime) else (collected.isoformat() if collected else None)
    source_type_label = SOURCE_TYPE_LABELS.get(source.source_type, source.source_type)
    reading = project_research_note_reading(
        summary=summary,
        claims=claims,
        evidence_by_claim=by_claim,
        source_type=source.source_type,
        source_type_label=source_type_label,
        author=author,
        collected_at=collected_iso,
        original_url=source.original_url,
        canonical_url=source.canonical_url,
    )
    latest_code = latest_run.status if latest_run else None
    waiting = latest_code in {"PENDING", "QUEUED", "RUNNING"}
    export_enabled = reading_has_body(reading) and not waiting
    analysis_progress = None
    if latest_run is not None and waiting:
        stage = read_stage(latest_run)
        progress_provider = {
            "DEEPSEEK": "DeepSeek",
            "SILICONFLOW": "SiliconFlow",
            "LOCAL_OPENAI_COMPATIBLE": "LM Studio",
            "GENERIC_OPENAI_COMPATIBLE": "Generic",
            "FAKE": "Fake",
        }.get(latest_run.provider_type or "", latest_run.provider_type or None)
        progress_model = latest_run.model_name
        if latest_run.status in {"PENDING", "QUEUED"} or not progress_model:
            try:
                route_spec = resolve_workflow(session, settings, "ANALYSIS", None)
                progress_provider = {
                    "DEEPSEEK": "DeepSeek",
                    "SILICONFLOW": "SiliconFlow",
                    "LOCAL_OPENAI_COMPATIBLE": "LM Studio",
                    "GENERIC_OPENAI_COMPATIBLE": "Generic",
                    "FAKE": "Fake",
                }.get(route_spec.provider_type, route_spec.name)
                progress_model = route_spec.model
            except Exception:
                pass
        analysis_progress = {
            "run_id": str(latest_run.id),
            "status": latest_run.status,
            "stage": stage,
            "stage_label": stage_label(stage),
            "provider": progress_provider,
            "model_name": progress_model,
        }

    partial_summary = None
    partial_issues: list[str] = []
    if content_run is not None and content_run.status == "PARTIAL" and result and result.raw_structured_json:
        issues = result.raw_structured_json.get("validation_issues") if isinstance(result.raw_structured_json, dict) else None
        if isinstance(issues, list) and issues:
            partial_issues = [str(issue)[:240] for issue in issues if isinstance(issue, str)][:50]
            partial_summary = f"已保留有效学习笔记，另有 {len(issues)} 项内容未通过来源依据校验。"

    return {
        "source_id": str(source.id),
        "title": title,
        "partial_summary": partial_summary,
        "partial_issues": partial_issues,
        "source_type": source.source_type,
        "source_type_label": source_type_label,
        "author": author,
        "original_url": source.original_url,
        "canonical_url": source.canonical_url,
        "collected_at": collected_iso,
        "analysis_status": status_label,
        "analysis_status_code": status_code,
        "analysis_latest_status_code": latest_code,
        "analysis_failure": analysis_failure,
        "reading": reading,
        "export_enabled": export_enabled,
        "analysis_progress": analysis_progress,
        "summary": summary,
        "highlights": highlights,
        "claim_groups": {CLAIM_GROUPS.get(key, key): grouped[key] for key in grouped},
        "categories": categories,
        "topics": topics,
        "entities": entities,
        "providers_configured": configured,
        "analysis": analysis_meta
            or {
                "provider": None,
                "model_name": run.model_name if run else None,
                "completed_at": run.completed_at.isoformat() if run and run.completed_at else None,
                "prompt_version": run.prompt_version if run else None,
                "is_cloud": None,
            },
        "ask_answer_model_hint": ask_route,
        "export_formats": ["markdown", "docx", "pdf"],
    }


def research_note_markdown(note: dict) -> str:
    if note.get("reading"):
        return research_note_markdown_from_note(note)
    lines = [f"# {note['title']}", ""]
    if note.get("summary"):
        lines.extend([f"> {note['summary']}", ""])
    if note.get("highlights"):
        lines.extend(["## 核心要点", ""])
        for item in note["highlights"]:
            text = item["text"] if isinstance(item, dict) else str(item)
            lines.append(f"- {text}")
        lines.append("")
    for heading, rows in (note.get("claim_groups") or {}).items():
        if not rows:
            continue
        lines.extend([f"## {heading}", ""])
        for row in rows:
            lines.append(f"- {row['text']}")
        lines.append("")
    if note.get("original_url") or note.get("canonical_url"):
        lines.extend(["## 来源与依据", "", note.get("original_url") or note.get("canonical_url") or "", ""])
    return "\n".join(lines).strip() + "\n"
