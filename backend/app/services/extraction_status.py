"""User-facing extraction status labels for inbox and notes."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.extraction import ExtractionRun, ExtractedDocument
from app.services.maintenance.system import worker_detected

EXTRACTION_STATUS_LABELS = {
    "SUCCEEDED": "正文已提取",
    "PARTIAL": "部分正文",
    "FAILED": "正文提取失败",
    "PENDING": "正在提取正文",
    "RUNNING": "正在提取正文",
}

EXTRACTION_USER_MESSAGES = {
    "NEEDS_BROWSER_EXTRACTION": "页面需要浏览器渲染，但尚未获得正文。",
    "WEB_AUTH_OR_CHALLENGE": "页面需要登录或验证，无法读取公开正文。",
    "WEB_EXTRACTION_LOW_QUALITY": "页面正文质量不足，可能只有导航或框架内容。",
    "WEB_EMPTY": "没有提取到正文。",
    "WEB_HTTP_ERROR": "网页返回错误，无法读取。",
    "WEB_TIMEOUT": "获取网页超时。",
    "SSRF_BLOCKED": "该 URL 不允许访问。",
    "BROWSER_RUNTIME_UNAVAILABLE": "需要浏览器渲染，但本机未安装 Chromium。",
    "BROWSER_AUTH_REQUIRED": "浏览器访问时遇到登录墙。",
    "BROWSER_CHALLENGE_DETECTED": "浏览器访问时遇到验证页面。",
    "WORKER_NOT_CONSUMING": "后台提取任务尚未开始，请确认 Worker 已启动。",
}


def _latest_extraction(session: Session, source_id: uuid.UUID) -> ExtractionRun | None:
    return session.scalar(
        select(ExtractionRun)
        .where(ExtractionRun.source_item_id == source_id)
        .order_by(ExtractionRun.created_at.desc())
        .limit(1)
    )


def extraction_status_for_source(session: Session, source_id: uuid.UUID) -> dict:
    run = _latest_extraction(session, source_id)
    if run is None:
        return {
            "extraction_status": "已保存",
            "extraction_status_code": "SAVED",
            "extraction_error_code": None,
            "extraction_user_message": None,
            "has_usable_content": False,
        }
    label = EXTRACTION_STATUS_LABELS.get(run.status, run.status)
    message = EXTRACTION_USER_MESSAGES.get(run.error_code or "", run.error_message)
    latest_doc = session.scalar(
        select(ExtractedDocument)
        .where(ExtractedDocument.source_item_id == source_id)
        .order_by(ExtractedDocument.created_at.desc())
        .limit(1)
    )
    completeness = (
        latest_doc.metadata_json.get("content_completeness")
        if latest_doc is not None and isinstance(latest_doc.metadata_json, dict)
        else None
    )
    # Metadata-only X descriptions are useful for display and provenance, but
    # are not article text and must not make Analysis appear available.
    has_usable = latest_doc is not None and completeness != "metadata_only" and (
        run.status in {"SUCCEEDED", "PARTIAL"}
        or completeness == "user_supplied"
        or session.scalar(
            select(ExtractionRun.id)
            .where(ExtractionRun.source_item_id == source_id, ExtractionRun.status.in_(("SUCCEEDED", "PARTIAL")))
            .limit(1)
        )
        is not None
    )
    if run.status in {"PENDING", "RUNNING"} and not worker_detected():
        label = "等待提取"
        message = EXTRACTION_USER_MESSAGES["WORKER_NOT_CONSUMING"]
        return {
            "extraction_status": label,
            "extraction_status_code": "WORKER_NOT_CONSUMING",
            "extraction_error_code": "WORKER_NOT_CONSUMING",
            "extraction_user_message": message,
            "has_usable_content": has_usable,
        }
    return {
        "extraction_status": label,
        "extraction_status_code": run.status,
        "extraction_error_code": run.error_code,
        "extraction_user_message": message if run.status == "FAILED" else None,
        "has_usable_content": has_usable,
    }
