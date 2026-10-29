"""Cover generation orchestration."""

from __future__ import annotations

import uuid
import re
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.analysis import LLMModelDeployment, LLMProviderConfig
from app.models.cover import CoverGenerationRun, SourceCoverAsset
from app.models.extraction import ExtractedDocument
from app.models.source_item import SourceItem
from app.services.cover.prompt import PROMPT_VERSION, build_default_cover_prompt, preview_token, prompt_hash, resolve_effective_cover_prompt
from app.services.cover.prompt_config import current_prompt_revision
from app.services.cover.budget import lock_monthly_budget
from app.services.cover.storage import CoverStorageError, save_cover_bytes
from app.services.display_title import resolve_display_title
from app.services.image.minimax import MinimaxImageError, generate_image
from app.services.image.minimax_contract import MAX_PROMPT_CHARS
from app.services.llm.deployments import list_deployments_for_provider
from app.services.research_note import content_analysis_summary


class CoverServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


ACTIVE_STATUSES = {"QUEUED", "GENERATING", "DECODING", "VALIDATING", "SAVING"}
TERMINAL_STATUSES = {"SUCCEEDED", "FAILED"}


class CoverGenerationService:
    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    def resolve_image_deployment(self) -> tuple[LLMModelDeployment, LLMProviderConfig]:
        provider = self.session.scalar(select(LLMProviderConfig).where(LLMProviderConfig.provider_type == "MINIMAX_IMAGE"))
        if provider is None or not provider.enabled:
            raise CoverServiceError("PROVIDER_NOT_CONFIGURED", "MiniMax 图像 Provider 未配置或未启用。", 409)
        deployments = [d for d in list_deployments_for_provider(self.session, provider.id) if d.enabled]
        if not deployments:
            raise CoverServiceError("DEPLOYMENT_NOT_FOUND", "没有可用的 MiniMax 图像模型部署。", 409)
        return deployments[0], provider

    def build_prompt_for_source(
        self,
        source_id: uuid.UUID,
        *,
        user_prompt: str | None = None,
        color_scheme: str = "auto",
        global_prompt: str | None = None,
        personalization: str | None = None,
    ) -> tuple[str, bool, SourceItem]:
        from app.models.organization import Category, SourceCategoryAssignment

        source = self.session.get(SourceItem, source_id)
        if source is None:
            raise CoverServiceError("SOURCE_NOT_FOUND", "找不到资料。", 404)
        if source.deleted_at is not None:
            raise CoverServiceError("SOURCE_IN_TRASH", "该资料已在最近删除中。", 409)
        prompt_config = current_prompt_revision(self.session)
        doc = self.session.scalar(
            select(ExtractedDocument).where(ExtractedDocument.source_item_id == source.id).order_by(ExtractedDocument.created_at.desc())
        )
        summary = content_analysis_summary(self.session, source.id)
        title = source.display_name
        if doc and doc.title:
            title = doc.title
        slugs: list[str] = []
        for row in self.session.scalars(
            select(SourceCategoryAssignment).where(SourceCategoryAssignment.source_item_id == source.id, SourceCategoryAssignment.status == "ACTIVE")
        ):
            category_row = self.session.get(Category, row.category_id)
            if category_row:
                slugs.append(category_row.slug)
        display_title = resolve_display_title(source, document_title=title if title and title != source.display_name else doc.title if doc else None, analysis_summary=summary)
        excerpt = (doc.plain_text[:400] if doc and doc.plain_text else None)
        recent_prompts = self.session.scalars(
            select(CoverGenerationRun.prompt)
            .where(CoverGenerationRun.status == "SUCCEEDED")
            .order_by(CoverGenerationRun.created_at.desc())
            .limit(12)
        )
        recent_palettes = [
            match.group(1)
            for value in recent_prompts
            if (match := re.search(r"Palette direction \(([^)]+)\):", value or ""))
        ]
        metadata_only = bool(
            doc is not None
            and isinstance(doc.metadata_json, dict)
            and doc.metadata_json.get("content_completeness") == "metadata_only"
        )
        prompt, usable = build_default_cover_prompt(
            title=display_title,
            source_type=source.source_type,
            summary=summary,
            plain_excerpt=excerpt,
            color_scheme=color_scheme,
            recent_palettes=recent_palettes,
            global_prompt=prompt_config.prompt if global_prompt is None else global_prompt,
            personalization=personalization,
        )
        if metadata_only:
            usable = False
        if user_prompt is not None and user_prompt.strip():
            try:
                prompt = resolve_effective_cover_prompt(default_prompt=prompt, edited_prompt=user_prompt)
            except ValueError as exc:
                message = str(exc)
                if message.startswith("COVER_PROMPT_TOO_LONG:"):
                    parts = message.split(":")
                    actual = parts[1] if len(parts) > 1 else "?"
                    raise CoverServiceError(
                        "COVER_PROMPT_TOO_LONG",
                        f"提示词过长（{actual}/{MAX_PROMPT_CHARS} 字符，阶段 user）。请精简视觉描述。",
                        400,
                    ) from exc
                raise
        return prompt, usable, source

    def enqueue(
        self,
        source_id: uuid.UUID,
        *,
        prompt: str | None,
        confirm_send: bool,
        auto: bool = False,
        color_scheme: str = "auto",
        idempotency_key: str | None = None,
        expected_prompt_revision: int | None = None,
        expected_prompt_token: str | None = None,
    ) -> CoverGenerationRun:
        if not confirm_send:
            raise CoverServiceError("CONFIRMATION_REQUIRED", "生成配图需要确认发送主题描述到 MiniMax。", 400)
        try:
            prompt_config = current_prompt_revision(self.session)
            if expected_prompt_revision is not None and expected_prompt_revision != prompt_config.revision:
                raise CoverServiceError("PROMPT_PREVIEW_STALE", "全局配图 Prompt 已更新，请刷新预览后重试。", 409)
            default_prompt, usable, source = self.build_prompt_for_source(
                source_id, user_prompt=None, color_scheme=color_scheme, global_prompt=prompt_config.prompt
            )
        except ValueError as exc:
            if str(exc) == "COVER_PALETTE_INVALID":
                raise CoverServiceError("COVER_PALETTE_INVALID", "请选择有效的封面配色方案。", 400) from exc
            raise
        if not usable:
            raise CoverServiceError("INSUFFICIENT_CONTENT", "目前没有足够的资料内容生成准确配图。", 409)
        if expected_prompt_token is not None and expected_prompt_token != preview_token(
            default_prompt, revision=prompt_config.revision, color_scheme=color_scheme
        ):
            raise CoverServiceError("PROMPT_PREVIEW_STALE", "资料内容或 Prompt 配置已变化，请刷新最终 Prompt 预览后重试。", 409)
        # Serialize submissions for this source even when automation skips the
        # paid provider budget lock. Different browser tabs share this lock.
        self.session.execute(select(SourceItem.id).where(SourceItem.id == source_id).with_for_update())
        idempotent_run_id = uuid.uuid5(source.id, idempotency_key) if idempotency_key else None
        if idempotent_run_id is not None:
            existing = self.session.get(CoverGenerationRun, idempotent_run_id)
            if existing is not None:
                return existing
        try:
            final_prompt = resolve_effective_cover_prompt(default_prompt=default_prompt, edited_prompt=prompt)
        except ValueError as exc:
            message = str(exc)
            if message.startswith("COVER_PROMPT_TOO_LONG:"):
                parts = message.split(":")
                actual = parts[1] if len(parts) > 1 else "?"
                stage = parts[3] if len(parts) > 3 else "submit"
                raise CoverServiceError(
                    "COVER_PROMPT_TOO_LONG",
                    f"提示词过长（{actual}/{MAX_PROMPT_CHARS} 字符，阶段 {stage}）。请精简视觉描述。",
                    400,
                ) from exc
            raise
        if not final_prompt:
            raise CoverServiceError("PROMPT_REQUIRED", "提示词不能为空。", 400)
        active = self.session.scalar(
            select(CoverGenerationRun)
            .where(CoverGenerationRun.source_item_id == source_id, CoverGenerationRun.status.in_(ACTIVE_STATUSES))
            .order_by(CoverGenerationRun.created_at.desc())
        )
        if active is not None:
            raise CoverServiceError("JOB_ALREADY_RUNNING", "该资料已有进行中的配图任务。", 409)
        deployment, _provider = self.resolve_image_deployment()
        from app.services.system_scope import AUTOMATION_TEST_SCOPE

        simulated_automation = self.settings.minimax_enable_fake and source.system_scope == AUTOMATION_TEST_SCOPE
        if not simulated_automation:
            try:
                used, budget = lock_monthly_budget(self.session, _provider.id, settings=self.settings)
            except LookupError as exc:
                raise CoverServiceError("PROVIDER_NOT_CONFIGURED", "MiniMax 图像 Provider 未配置。", 409) from exc
            if used >= budget:
                raise CoverServiceError(
                    "COVER_MONTHLY_BUDGET_EXCEEDED",
                    f"本月配图预算已用尽（{used}/{budget} 次生成尝试），为避免超额费用已阻止本次调用。",
                    409,
                )
        # A concurrent retry with the same client key may have committed while
        # this request waited for the provider budget lock.
        if idempotent_run_id is not None:
            existing = self.session.get(CoverGenerationRun, idempotent_run_id)
            if existing is not None:
                self.session.rollback()
                return existing
        active = self.session.scalar(
            select(CoverGenerationRun)
            .where(CoverGenerationRun.source_item_id == source_id, CoverGenerationRun.status.in_(ACTIVE_STATUSES))
            .order_by(CoverGenerationRun.created_at.desc())
        )
        if active is not None:
            raise CoverServiceError("JOB_ALREADY_RUNNING", "该资料已有进行中的配图任务。", 409)
        now = datetime.now(timezone.utc)
        run = CoverGenerationRun(
            id=idempotent_run_id or uuid.uuid4(),
            source_item_id=source_id,
            deployment_id=deployment.id,
            status="QUEUED",
            stage="QUEUED",
            prompt=final_prompt,
            prompt_version=f"{PROMPT_VERSION}-r{prompt_config.revision}",
            candidate_review_state=None,
            created_at=now,
            updated_at=now,
        )
        self.session.add(run)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.session.get(CoverGenerationRun, run.id) if idempotent_run_id is not None else None
            if existing is None:
                raise
            return existing
        if self.settings.cover_inline:
            self.execute(run.id)
        else:
            from app.jobs.cover_generation import enqueue_cover_generation
            try:
                enqueue_cover_generation(str(run.id))
            except Exception as exc:
                self._fail_run(run, "QUEUE_UNAVAILABLE", "配图任务未能进入队列。")
                raise CoverServiceError("QUEUE_UNAVAILABLE", "配图任务未能进入队列。", 503) from exc
        return run

    def execute(self, run_id: uuid.UUID) -> CoverGenerationRun:
        run = self.session.get(CoverGenerationRun, run_id)
        if run is None:
            raise CoverServiceError("RUN_NOT_FOUND", "找不到配图任务。", 404)
        claimed = self.session.execute(
            update(CoverGenerationRun)
            .where(CoverGenerationRun.id == run_id, CoverGenerationRun.status == "QUEUED")
            .values(status="GENERATING", stage="GENERATING", updated_at=datetime.now(timezone.utc))
            .returning(CoverGenerationRun.id)
        ).scalar_one_or_none()
        self.session.commit()
        self.session.refresh(run)
        if claimed is None:
            return run
        deployment = self.session.get(LLMModelDeployment, run.deployment_id)
        provider = self.session.get(LLMProviderConfig, deployment.provider_config_id) if deployment else None
        try:
            self._set_stage(run, "GENERATING")
            result = generate_image(
                run.prompt,
                model=deployment.model_id if deployment else None,
                settings=self.settings,
                session=self.session,
            )
            if not result.ok or not result.image_bytes:
                raise CoverServiceError(result.code or "GENERATION_FAILED", result.message or "生成失败。", 502)
            self._set_stage(run, "DECODING")
            self._set_stage(run, "VALIDATING")
            self._set_stage(run, "SAVING")
            relative, content_hash, _ext = save_cover_bytes(run.source_item_id, result.image_bytes, self.settings)
            from app.services.cover.verification import verify_asset_file

            verified, vcode = verify_asset_file(relative)
            if not verified:
                raise CoverServiceError(vcode or "COVER_PERSISTENCE_FAILED", "配图文件未能通过持久化校验。", 502)
            asset = SourceCoverAsset(
                id=uuid.uuid4(),
                source_item_id=run.source_item_id,
                kind="GENERATED",
                provider_type=provider.provider_type if provider else "MINIMAX_IMAGE",
                model_id=deployment.model_id if deployment else None,
                prompt_hash=prompt_hash(run.prompt),
                content_hash=content_hash,
                relative_path=relative,
                # Generation creates a review candidate. The existing current
                # asset remains authoritative until the user explicitly applies it.
                is_current=False,
                generation_run_id=run.id,
            )
            self.session.add(asset)
            run.asset_id = asset.id
            run.status = "SUCCEEDED"
            run.stage = "SUCCEEDED"
            run.error_code = None
            run.error_message = None
            run.updated_at = datetime.now(timezone.utc)
            self.session.commit()
            return run
        except (CoverStorageError, MinimaxImageError, CoverServiceError) as exc:
            self._fail_run(run, getattr(exc, "code", "FAILED"), getattr(exc, "message", str(exc)))
            return run
        except Exception as exc:
            self._fail_run(run, "WORKER_ERROR", "配图任务异常终止，请重试。")
            from app.core.logging import log_event

            log_event("cover_generation_failed", run_id=str(run.id), message=type(exc).__name__)
            return run

    def _fail_run(self, run: CoverGenerationRun, code: str, message: str) -> None:
        run.status = "FAILED"
        run.stage = "FAILED"
        run.error_code = code
        run.error_message = message
        run.updated_at = datetime.now(timezone.utc)
        self.session.commit()

    def _set_stage(self, run: CoverGenerationRun, stage: str) -> None:
        run.stage = stage
        run.status = stage if stage in ACTIVE_STATUSES else run.status
        run.updated_at = datetime.now(timezone.utc)
        self.session.commit()

    def latest_run(self, source_id: uuid.UUID) -> CoverGenerationRun | None:
        return self.session.scalar(
            select(CoverGenerationRun)
            .where(CoverGenerationRun.source_item_id == source_id)
            .order_by(CoverGenerationRun.created_at.desc())
        )

    def retry_failed_run(self, run_id: uuid.UUID, *, confirm_send: bool) -> CoverGenerationRun:
        from app.services.cover.verification import effective_run_success

        run = self.session.get(CoverGenerationRun, run_id)
        if run is None:
            raise CoverServiceError("RUN_NOT_FOUND", "找不到配图任务。", 404)
        source = self.session.get(SourceItem, run.source_item_id)
        if source is None or source.deleted_at is not None:
            raise CoverServiceError("SOURCE_NOT_FOUND", "资料不存在或已删除。", 404)
        if run.status in ACTIVE_STATUSES:
            raise CoverServiceError("JOB_ALREADY_RUNNING", "该资料已有进行中的配图任务。", 409)
        ok, _err = effective_run_success(self.session, run)
        if ok:
            raise CoverServiceError("ALREADY_SUCCEEDED", "配图已可用，无需重新生成。", 409)
        if run.status == "SUCCEEDED":
            raise CoverServiceError("COVER_PERSISTENCE_FAILED", "上次任务标记成功但图片不可用，请重新生成。", 409)
        if run.status != "FAILED":
            raise CoverServiceError("RETRY_NOT_ALLOWED", "仅失败任务可重试。", 409)
        if not confirm_send:
            raise CoverServiceError("CONFIRMATION_REQUIRED", "重新生成配图需要确认发送到 MiniMax。", 400)
        return self.enqueue(run.source_item_id, prompt=None, confirm_send=True, auto=False)

    def apply_candidate(self, run_id: uuid.UUID) -> CoverGenerationRun:
        from app.services.cover.verification import effective_run_success

        run = self.session.scalar(
            select(CoverGenerationRun).where(CoverGenerationRun.id == run_id).with_for_update()
        )
        if run is None:
            raise CoverServiceError("RUN_NOT_FOUND", "找不到配图任务。", 404)
        if run.status != "SUCCEEDED" or run.asset_id is None:
            raise CoverServiceError("CANDIDATE_NOT_READY", "新封面尚未生成成功，不能应用。", 409)
        self.session.execute(select(SourceItem.id).where(SourceItem.id == run.source_item_id).with_for_update())
        asset = self.session.get(SourceCoverAsset, run.asset_id)
        if asset is None or asset.source_item_id != run.source_item_id or asset.kind != "GENERATED" or asset.generation_run_id != run.id:
            raise CoverServiceError("CANDIDATE_NOT_FOUND", "找不到该生成任务的候选封面。", 409)
        ok, error = effective_run_success(self.session, run)
        if not ok:
            raise CoverServiceError(error or "COVER_ASSET_UNAVAILABLE", "候选封面无法通过文件校验。", 409)
        current = list(
            self.session.scalars(
                select(SourceCoverAsset)
                .where(SourceCoverAsset.source_item_id == run.source_item_id, SourceCoverAsset.is_current.is_(True))
                .with_for_update()
            )
        )
        try:
            for previous in current:
                self.session.execute(
                    update(SourceCoverAsset).where(SourceCoverAsset.id == previous.id).values(is_current=False)
                )
            self.session.flush()
            asset.is_current = True
            run.candidate_review_state = "APPLIED"
            run.updated_at = datetime.now(timezone.utc)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        self.session.refresh(run)
        return run

    def keep_current(self, run_id: uuid.UUID) -> CoverGenerationRun:
        run = self.session.scalar(
            select(CoverGenerationRun).where(CoverGenerationRun.id == run_id).with_for_update()
        )
        if run is None:
            raise CoverServiceError("RUN_NOT_FOUND", "找不到配图任务。", 404)
        if run.status != "SUCCEEDED" or run.asset_id is None:
            raise CoverServiceError("CANDIDATE_NOT_READY", "没有可供审阅的候选封面。", 409)
        asset = self.session.get(SourceCoverAsset, run.asset_id)
        if asset is None or asset.kind != "GENERATED" or asset.generation_run_id != run.id:
            raise CoverServiceError("CANDIDATE_NOT_FOUND", "找不到该生成任务的候选封面。", 409)
        if asset.is_current:
            raise CoverServiceError("CANDIDATE_ALREADY_APPLIED", "该封面已设为当前封面。", 409)
        run.candidate_review_state = "KEPT_OLD"
        run.updated_at = datetime.now(timezone.utc)
        self.session.commit()
        self.session.refresh(run)
        return run

    def current_generated_asset(self, source_id: uuid.UUID) -> SourceCoverAsset | None:
        return self.session.scalar(
            select(SourceCoverAsset).where(
                SourceCoverAsset.source_item_id == source_id,
                SourceCoverAsset.is_current.is_(True),
                SourceCoverAsset.kind == "GENERATED",
            )
        )
