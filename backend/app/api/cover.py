import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.session import get_db
from app.services.cover.auto import audit_cover_funnel, enqueue_backfill_missing, scan_and_enqueue_auto_covers
from app.services.cover.budget import monthly_budget_usage_count
from app.services.cover.queue import cover_queue_summary, list_cover_jobs
from app.services.cover.service import CoverGenerationService, CoverServiceError
from app.services.cover.settings_prefs import (
    MAX_COVER_MONTHLY_BUDGET,
    MIN_COVER_MONTHLY_BUDGET,
    load_cover_prefs,
    save_cover_auto_enabled,
    save_cover_monthly_budget,
)
from app.services.cover.prompt import DEFAULT_GLOBAL_PROMPT, GLOBAL_PROMPT_MAX_CHARS, preview_token
from app.services.cover.prompt_config import create_prompt_revision, current_prompt_revision, validate_global_prompt
from app.services.cover.status_view import build_cover_status_payload
from app.services.image.minimax_contract import DEFAULT_PROMPT_TARGET_CHARS, MAX_PROMPT_CHARS, prompt_char_count
from app.core.config import get_settings
from app.services.system_scope import scope_visible_for_api
from app.models.cover import CoverGenerationRun
from app.models.source_item import SourceItem

router = APIRouter(prefix="/api", tags=["cover"])


class CoverGenerateBody(BaseModel):
    prompt: str | None = None
    confirm_send: bool = Field(default=False)
    retry_failed_only: bool = Field(default=False)
    color_scheme: Literal["auto", "cool", "neutral", "warm", "high_contrast", "low_saturation", "vivid"] = "auto"
    idempotency_key: uuid.UUID | None = None
    prompt_revision: int | None = Field(default=None, ge=1)
    prompt_preview_token: str | None = Field(default=None, min_length=64, max_length=64)


class GlobalCoverPromptBody(BaseModel):
    prompt: str = Field(max_length=GLOBAL_PROMPT_MAX_CHARS)


class CoverPromptPreviewBody(BaseModel):
    source_id: uuid.UUID
    global_prompt: str | None = Field(default=None, max_length=GLOBAL_PROMPT_MAX_CHARS)
    color_scheme: Literal["auto", "cool", "neutral", "warm", "high_contrast", "low_saturation", "vivid"] = "auto"
    personalization: str = Field(default="", max_length=160)


class CoverRetryBody(BaseModel):
    confirm_send: bool = Field(default=False)


class CoverCandidateReviewBody(BaseModel):
    action: Literal["keep_old", "use_new"]


class CoverBackfillBody(BaseModel):
    source_ids: list[uuid.UUID] | None = None
    confirm: bool = Field(default=False)
    retry_failed_only: bool = Field(default=False)


class CoverSettingsPatch(BaseModel):
    auto_enabled: bool | None = None
    monthly_budget: int | None = Field(default=None, ge=MIN_COVER_MONTHLY_BUDGET, le=MAX_COVER_MONTHLY_BUDGET)


@router.get("/sources/{source_id}/cover/prompt")
def cover_prompt_preview(
    source_id: uuid.UUID,
    color_scheme: Literal["auto", "cool", "neutral", "warm", "high_contrast", "low_saturation", "vivid"] = "auto",
    session: Session = Depends(get_db),
):
    source = session.get(SourceItem, source_id)
    if source is None or not scope_visible_for_api(source.system_scope):
        return {"ok": False, "code": "SOURCE_NOT_FOUND"}
    service = CoverGenerationService(session)
    prompt_revision = current_prompt_revision(session)
    prompt, usable, _ = service.build_prompt_for_source(
        source_id, color_scheme=color_scheme, global_prompt=prompt_revision.prompt
    )
    deployment, provider = service.resolve_image_deployment()
    prefs = load_cover_prefs(session)
    budget_used = monthly_budget_usage_count(session)
    from app.models.extraction import ExtractedDocument
    from app.services.cover.resolution import resolve_cover

    doc = session.scalar(
        select(ExtractedDocument).where(ExtractedDocument.source_item_id == source_id).order_by(ExtractedDocument.created_at.desc())
    )
    resolved = resolve_cover(session, source_id, doc)
    current_asset = service.current_generated_asset(source_id)
    current_version = str(current_asset.id) if current_asset else str(int(source.updated_at.timestamp()))
    return {
        "ok": True,
        "title": source.display_name,
        "prompt": prompt,
        "prompt_char_count": prompt_char_count(prompt),
        "max_prompt_chars": MAX_PROMPT_CHARS,
        "default_target_chars": DEFAULT_PROMPT_TARGET_CHARS,
        "content_usable": usable,
        "model": deployment.model_id,
        "provider": provider.name,
        "color_scheme": color_scheme,
        "budget_used": budget_used,
        "monthly_budget": prefs.monthly_budget,
        "budget_kind": "insighthub_local_safety_cap",
        "budget_range": {"min": MIN_COVER_MONTHLY_BUDGET, "max": MAX_COVER_MONTHLY_BUDGET},
        "budget_available": budget_used < prefs.monthly_budget,
        "current_cover_url": f"/api/sources/{source_id}/cover-image?v={current_version}" if resolved else None,
        "prompt_revision": prompt_revision.revision,
        "prompt_version": prompt_revision.version,
        "prompt_preview_token": preview_token(
            prompt,
            revision=prompt_revision.revision,
            color_scheme=color_scheme,
        ),
    }


@router.get("/cover/audit")
def cover_audit(session: Session = Depends(get_db)):
    settings = get_settings()
    return {"ok": True, **audit_cover_funnel(session, settings=settings)}


def _prompt_revision_payload(row):
    return {
        "revision": row.revision,
        "version": row.version,
        "prompt": row.prompt,
        "updated_at": row.created_at.isoformat() if row.created_at else None,
        "max_global_prompt_chars": GLOBAL_PROMPT_MAX_CHARS,
        "system_default_prompt": DEFAULT_GLOBAL_PROMPT,
    }


@router.get("/cover/prompt-config")
def cover_prompt_config(session: Session = Depends(get_db)):
    return {"ok": True, **_prompt_revision_payload(current_prompt_revision(session))}


@router.put("/cover/prompt-config")
def update_cover_prompt_config(body: GlobalCoverPromptBody, request: Request, session: Session = Depends(get_db)):
    from app.api.local_guard import require_local_settings_mutation

    require_local_settings_mutation(request)
    try:
        prompt = validate_global_prompt(body.prompt)
    except ValueError as exc:
        code = str(exc)
        message = "全局 Prompt 不能为空。" if code == "COVER_GLOBAL_PROMPT_REQUIRED" else f"全局 Prompt 不能超过 {GLOBAL_PROMPT_MAX_CHARS} 个字符。"
        return {"ok": False, "code": code, "message": message}
    row = create_prompt_revision(session, prompt)
    return {"ok": True, **_prompt_revision_payload(row)}


@router.post("/cover/prompt-config/reset")
def reset_cover_prompt_config(request: Request, session: Session = Depends(get_db)):
    from app.api.local_guard import require_local_settings_mutation

    require_local_settings_mutation(request)
    row = create_prompt_revision(session, DEFAULT_GLOBAL_PROMPT, version="system-default-r1")
    return {"ok": True, **_prompt_revision_payload(row)}


@router.post("/cover/prompt-preview")
def preview_cover_prompt(body: CoverPromptPreviewBody, session: Session = Depends(get_db)):
    source = session.get(SourceItem, body.source_id)
    if source is None or not scope_visible_for_api(source.system_scope):
        return {"ok": False, "code": "SOURCE_NOT_FOUND"}
    if body.global_prompt is not None:
        try:
            validate_global_prompt(body.global_prompt)
        except ValueError as exc:
            return {"ok": False, "code": str(exc), "message": "请先填写有效的全局 Prompt。"}
    try:
        prompt, usable, _source = CoverGenerationService(session).build_prompt_for_source(
            body.source_id,
            color_scheme=body.color_scheme,
            global_prompt=body.global_prompt,
            personalization=body.personalization,
        )
    except (CoverServiceError, ValueError) as exc:
        return {"ok": False, "code": getattr(exc, "code", str(exc)), "message": getattr(exc, "message", "Prompt 无法构建。")}
    revision = current_prompt_revision(session)
    return {
        "ok": True,
        "source_id": str(source.id),
        "title": source.display_name,
        "prompt": prompt,
        "prompt_char_count": prompt_char_count(prompt),
        "max_prompt_chars": MAX_PROMPT_CHARS,
        "content_usable": usable,
        "global_prompt": revision.prompt if body.global_prompt is None else validate_global_prompt(body.global_prompt),
        "prompt_revision": revision.revision,
        "prompt_version": (
            f"draft-based-on-{revision.version}"
            if body.global_prompt is not None and validate_global_prompt(body.global_prompt) != revision.prompt
            else revision.version
        ),
        "color_scheme": body.color_scheme,
        "personalization": body.personalization,
        "topic": prompt.partition("Article topic and visual subject: ")[2].partition(". Palette direction (")[0],
        "palette_direction": prompt.partition("Palette direction (")[2].split("): ", 1)[-1].split(".", 1)[0],
    }


@router.get("/cover/settings")
def cover_settings(session: Session = Depends(get_db)):
    prefs = load_cover_prefs(session)
    return {
        "ok": True,
        "auto_enabled": prefs.auto_enabled,
        "requires_analysis": prefs.requires_analysis,
        "monthly_budget": prefs.monthly_budget,
        "budget_range": {"min": MIN_COVER_MONTHLY_BUDGET, "max": MAX_COVER_MONTHLY_BUDGET},
        "max_prompt_chars": MAX_PROMPT_CHARS,
        "default_target_chars": DEFAULT_PROMPT_TARGET_CHARS,
    }


@router.patch("/cover/settings")
def cover_settings_patch(body: CoverSettingsPatch, request: Request, session: Session = Depends(get_db)):
    from app.api.local_guard import require_local_settings_mutation

    require_local_settings_mutation(request)
    if body.auto_enabled is None and body.monthly_budget is None:
        raise HTTPException(status_code=422, detail="请提供自动配图开关或自定义安全上限。")
    try:
        prefs = load_cover_prefs(session)
        if body.monthly_budget is not None:
            prefs = save_cover_monthly_budget(session, body.monthly_budget)
        if body.auto_enabled is not None:
            prefs = save_cover_auto_enabled(session, body.auto_enabled)
    except ValueError as exc:
        if str(exc) == "MONTHLY_BUDGET_OUT_OF_RANGE":
            raise HTTPException(status_code=422, detail="本地安全上限必须在 1 至 500 次尝试/月之间。") from exc
        raise HTTPException(status_code=409, detail="MiniMax 图片 Provider 尚未配置，无法保存安全上限。") from exc
    settings = get_settings()
    scan = (
        scan_and_enqueue_auto_covers(session, settings=settings)
        if body.auto_enabled is True and settings.insighthub_system_scope != "AUTOMATION_TEST"
        else None
    )
    return {
        "ok": True,
        "auto_enabled": prefs.auto_enabled,
        "requires_analysis": prefs.requires_analysis,
        "monthly_budget": prefs.monthly_budget,
        "budget_range": {"min": MIN_COVER_MONTHLY_BUDGET, "max": MAX_COVER_MONTHLY_BUDGET},
        "budget_kind": "insighthub_local_safety_cap",
        "auto_scan": scan,
    }


@router.get("/cover/token-plan")
def cover_token_plan(session: Session = Depends(get_db)):
    """Manually refresh read-only MiniMax subscription quota status."""
    from app.services.image.minimax import probe_token_plan

    return {"ok": True, "provider": "MINIMAX_IMAGE", "mode": "subscription", **probe_token_plan(session=session)}


@router.get("/cover/queue")
def cover_queue(session: Session = Depends(get_db), limit: int = Query(default=40, ge=1, le=100)):
    return {"ok": True, "summary": cover_queue_summary(session), "jobs": list_cover_jobs(session, limit=limit)}


@router.get("/cover/runs/{run_id}")
def cover_run_detail(run_id: uuid.UUID, session: Session = Depends(get_db)):
    from app.models.cover import CoverGenerationRun
    from app.services.cover.verification import effective_run_success

    run = session.get(CoverGenerationRun, run_id)
    if run is None:
        return {"ok": False, "code": "RUN_NOT_FOUND"}
    source = session.get(SourceItem, run.source_item_id)
    if source is None or not scope_visible_for_api(source.system_scope):
        return {"ok": False, "code": "SOURCE_NOT_FOUND"}
    ok, err = effective_run_success(session, run)
    return {
        "ok": True,
        "run_id": str(run.id),
        "source_id": str(run.source_item_id),
        "source_title": source.display_name,
        "status": run.status,
        "stage": run.stage,
        "terminal_success": ok,
        "error_code": run.error_code if not ok else err,
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "prompt_preview": (run.prompt or "")[:240],
    }


@router.post("/cover/runs/{run_id}/retry")
def cover_run_retry(run_id: uuid.UUID, body: CoverRetryBody, session: Session = Depends(get_db)):
    service = CoverGenerationService(session)
    try:
        run = service.retry_failed_run(run_id, confirm_send=body.confirm_send)
    except CoverServiceError as exc:
        return {"ok": False, "code": exc.code, "message": exc.message}
    return {"ok": True, **build_cover_status_payload(session, run.source_item_id, run=run)}


@router.post("/cover/runs/{run_id}/review")
def cover_candidate_review(run_id: uuid.UUID, body: CoverCandidateReviewBody, session: Session = Depends(get_db)):
    run = session.get(CoverGenerationRun, run_id)
    source = session.get(SourceItem, run.source_item_id) if run is not None else None
    if source is None or not scope_visible_for_api(source.system_scope):
        return {"ok": False, "code": "RUN_NOT_FOUND", "message": "找不到配图任务。"}
    service = CoverGenerationService(session)
    try:
        run = service.apply_candidate(run_id) if body.action == "use_new" else service.keep_current(run_id)
    except CoverServiceError as exc:
        return {"ok": False, "code": exc.code, "message": exc.message}
    return {"ok": True, **build_cover_status_payload(session, run.source_item_id, run=run)}


@router.post("/cover/backfill")
def cover_backfill(body: CoverBackfillBody, session: Session = Depends(get_db)):
    settings = get_settings()
    try:
        result = enqueue_backfill_missing(
            session,
            source_ids=body.source_ids,
            confirm=body.confirm,
            retry_failed_only=body.retry_failed_only,
            settings=settings,
        )
    except CoverServiceError as exc:
        return {"ok": False, "code": exc.code, "message": exc.message}
    return {"ok": True, **result}


@router.post("/sources/{source_id}/cover/generate")
def cover_generate(source_id: uuid.UUID, body: CoverGenerateBody, session: Session = Depends(get_db)):
    source = session.get(SourceItem, source_id)
    if source is None or not scope_visible_for_api(source.system_scope):
        return {"ok": False, "code": "SOURCE_NOT_FOUND"}
    service = CoverGenerationService(session)
    try:
        run = service.enqueue(
            source_id,
            prompt=body.prompt,
            confirm_send=body.confirm_send,
            color_scheme=body.color_scheme,
            idempotency_key=str(body.idempotency_key) if body.idempotency_key else None,
            expected_prompt_revision=body.prompt_revision,
            expected_prompt_token=body.prompt_preview_token,
        )
    except CoverServiceError as exc:
        return {"ok": False, "code": exc.code, "message": exc.message}
    return build_cover_status_payload(session, source_id, run=run)


@router.get("/sources/{source_id}/cover/status")
def cover_status(
    source_id: uuid.UUID,
    run_id: uuid.UUID | None = Query(default=None),
    session: Session = Depends(get_db),
):
    from app.models.cover import CoverGenerationRun

    source = session.get(SourceItem, source_id)
    if source is None or not scope_visible_for_api(source.system_scope):
        return {"ok": False, "code": "SOURCE_NOT_FOUND"}
    service = CoverGenerationService(session)
    run = session.get(CoverGenerationRun, run_id) if run_id else service.latest_run(source_id)
    if run is not None and run.source_item_id != source_id:
        return {"ok": False, "code": "RUN_NOT_FOUND"}
    return build_cover_status_payload(session, source_id, run=run)
