import json
import re
import traceback
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy import cast
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.models.analysis import AnalysisResult, AnalysisRun, Claim, Evidence, LLMProviderConfig
from app.models.extraction import ContentChunk, ExtractedDocument, ExtractionRun
from app.models.source_item import SourceItem
from app.services.analysis.budget import (
    ProviderLimits,
    estimate_tokens,
    merge_payload_char_limit,
    raised_output_budget,
    resolve_provider_limits,
    chunk_groups_budget,
)
from app.services.analysis.schema import (
    PROMPT_NAME,
    PROMPT_VERSION,
    SourceAnalysis,
    Statement,
    load_prompt,
    load_schema,
    analysis_output_budget,
    output_language,
    parse_analysis,
    render_user,
    repair_output_budget,
)
from app.services.analysis.stages import (
    STAGE_CALLING_MODEL,
    STAGE_FAILED,
    STAGE_PARTIAL,
    STAGE_PREPARING,
    STAGE_QUEUED,
    STAGE_SAVING,
    STAGE_SUCCEEDED,
    STAGE_VALIDATING,
    set_analysis_stage,
)
from app.services.llm.fallback import RETRYABLE, select_fallback
from app.services.llm.provider import FakeLLMProvider
from app.services.llm.registry import ProviderSpec, build_provider, endpoint_configured, provider_specs, sync_provider_rows
from app.services.llm.types import LLMError, LLMRequest, LLMResponse


class AnalysisError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


_EMPTY_INPUT_MARKERS = (
    "no source text provided",
    "no source text",
    "source text was not provided",
    "未提供来源",
    "未提供源文本",
    "没有提供来源",
    "没有可分析的正文",
    "没有提供可分析",
    "未提供可分析",
    "无法提取事实",
    "无法提炼事实",
    "（无摘要）",
)
def user_has_source_text(user: str) -> bool:
    start = user.find("<source_content>")
    end = user.find("</source_content>")
    if start < 0 or end <= start:
        return bool(user.strip())
    return bool(user[start + len("<source_content>") : end].strip())


def source_body(chunks: list[ContentChunk]) -> str:
    return "\n".join((chunk.content or "").strip() for chunk in chunks if (chunk.content or "").strip())


_ORDERED_LIST_LINE = re.compile(r"(?m)^\s*(?:0?[1-9]|10)[.)]?\s+[\w\u4e00-\u9fff]")


def is_compact_image_list(source: SourceItem, document: ExtractedDocument, chunks: list[ContentChunk]) -> bool:
    """Recognize short OCR-derived list screenshots without changing extraction or validation."""
    if source.source_type != "IMAGE" or document.extractor_type != "IMAGE_OCR":
        return False
    body = source_body(chunks)
    return len(body) <= 2400 and len(_ORDERED_LIST_LINE.findall(body)) >= 6





def empty_input_summary(summary: str | None) -> bool:
    text = _norm(summary or "").casefold()
    return any(marker in text for marker in _EMPTY_INPUT_MARKERS)


def semantic_empty_result(parsed: SourceAnalysis) -> bool:
    if not empty_input_summary(parsed.summary):
        return False
    return not any((parsed.facts, parsed.source_claims, parsed.inferences, parsed.hypotheses))


def _has_analysis_content(parsed: SourceAnalysis) -> bool:
    return any((parsed.facts, parsed.source_claims, parsed.inferences, parsed.hypotheses, parsed.unknowns, parsed.questions))


def _needs_output_room(response: LLMResponse, parsed: SourceAnalysis | None) -> bool:
    """Reasoning models spend max_tokens before the visible JSON. A length cutoff with no analysis is not a result."""
    if response.finish_reason != "length":
        return False
    if not (response.text or "").strip() or parsed is None:
        return True
    return semantic_empty_result(parsed) or not _has_analysis_content(parsed)


def format_chunk(chunk: ContentChunk) -> str:
    heading = " / ".join(chunk.heading_path or [])
    page = (chunk.metadata_json or {}).get("page_number")
    page_line = f"Page: {page}\n" if page is not None else ""
    return f"[CHUNK: {chunk.id}]\nHeading: {heading}\n{page_line}Content:\n{chunk.content}\n"


def _safe_analysis_exception(exc: Exception, provider: object | None) -> str:
    """Capture an unexpected stack without locals, after removing the active provider key."""
    rendered = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    api_key = getattr(provider, "api_key", "") if provider is not None else ""
    if isinstance(api_key, str) and api_key:
        rendered = rendered.replace(api_key, "[REDACTED]")
    rendered = re.sub(r"(?i)(bearer\s+)[^\s\"']+", r"\1[REDACTED]", rendered)
    rendered = re.sub(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,\"']+", r"\1[REDACTED]", rendered)
    rendered = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED]", rendered)
    return rendered[-16000:]


def _metadata_dict(value: object) -> dict:
    """Normalize legacy JSONB concat results while retaining any object fields."""
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return _metadata_dict(decoded)
    if isinstance(value, list):
        merged: dict = {}
        for item in value:
            merged.update(_metadata_dict(item))
        return merged
    return {}


class AnalysisService:
    def __init__(self, session: Session, *, inline: bool, settings, enqueue=None, providers: dict | None = None) -> None:
        self.session = session
        self.inline = inline
        self.settings = settings
        self.enqueue = enqueue
        self.providers = providers or {}

    def start(self, source_id: uuid.UUID, provider_type: str | None = None) -> AnalysisRun:
        active = self.session.scalar(
            select(AnalysisRun)
            .where(AnalysisRun.source_item_id == source_id, AnalysisRun.status.in_(("PENDING", "RUNNING")))
            .order_by(AnalysisRun.created_at.desc())
        )
        if active is not None:
            raise AnalysisError(409, "ANALYSIS_ALREADY_RUNNING", "该资料已有进行中的分析任务。")
        source, document, chunks, extraction_status = self._inputs(source_id)
        spec = self._select(provider_type)
        self._require_fake_scope(source, spec)
        self._check_privacy(source, spec)
        rows = sync_provider_rows(self.session, self.settings)
        config = next(row for row in rows if row.provider_type == spec.provider_type)
        run_id = uuid.uuid4()
        run = AnalysisRun(
            id=run_id,
            source_item_id=source.id,
            extracted_document_id=document.id,
            provider_config_id=config.id,
            provider_type=spec.provider_type,
            model_name=spec.model,
            prompt_name=PROMPT_NAME,
            prompt_version=PROMPT_VERSION,
            status="PENDING",
            is_current=False,
            input_extraction_status=extraction_status,
            metadata_json={
                "deployment_id": str(spec.deployment_id) if spec.deployment_id else None,
            },
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(run)
        self.session.commit()
        set_analysis_stage(self.session, run, STAGE_QUEUED)
        if self.inline:
            return self.execute(run.id)
        if self.enqueue is None:
            return self._fail(run, "PROVIDER_UNAVAILABLE", "分析任务没有进入队列。")
        try:
            job_id = self.enqueue(str(run.id))
            if job_id:
                self.session.execute(
                    update(AnalysisRun)
                    .where(AnalysisRun.id == run.id)
                    .values(metadata_json=AnalysisRun.metadata_json.op("||")(cast({"rq_job_id": str(job_id)}, JSONB)))
                )
                self.session.commit()
        except Exception as exc:
            return self._fail(run, "PROVIDER_UNAVAILABLE", type(exc).__name__)
        self.session.refresh(run)
        return run

    def execute(self, run_id: uuid.UUID) -> AnalysisRun:
        now = datetime.now(timezone.utc)
        claimed = self.session.execute(
            update(AnalysisRun)
            .where(AnalysisRun.id == run_id, AnalysisRun.status == "PENDING")
            .values(status="RUNNING", started_at=now)
            .returning(AnalysisRun.id)
            .execution_options(synchronize_session=False)
        ).scalar_one_or_none()
        self.session.commit()
        run = self.session.get(AnalysisRun, run_id)
        if run is None:
            raise AnalysisError(404, "ANALYSIS_NOT_FOUND", "找不到分析任务。")
        # Duplicate, delayed, or already-recovered RQ deliveries are no-ops.
        if claimed is None:
            return run
        set_analysis_stage(self.session, run, STAGE_PREPARING)
        requested_provider_type = run.provider_type
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "latency_ms": 0, "calls": 0, "output_strategy": None, "schema_notice": None, "finish_reason": None}
        try:
            source = self.session.get(SourceItem, run.source_item_id)
            document = self.session.get(ExtractedDocument, run.extracted_document_id)
            chunks = list(self.session.scalars(select(ContentChunk).where(ContentChunk.extracted_document_id == document.id).order_by(ContentChunk.sequence.asc())).all())
            if self.settings.llm_enable_fake and "FAKE" in self.providers and source.system_scope == "AUTOMATION_TEST":
                spec = next(item for item in provider_specs(self.settings) if item.provider_type == "FAKE")
                provider = self.providers["FAKE"]
            else:
                spec = self._select(run.provider_type)
                provider = self.providers.get(spec.provider_type) or build_provider(spec, self.settings, session=self.session)
            self._require_fake_scope(source, spec)
            self._check_privacy(source, spec)
            run.model_name = getattr(provider, "model", spec.model)
            run.provider_type = getattr(provider, "provider_type", spec.provider_type)
            actual_config_id = spec.provider_config_id
            if actual_config_id is None:
                actual_config_id = self.session.scalar(
                    select(LLMProviderConfig.id).where(LLMProviderConfig.provider_type == run.provider_type).limit(1)
                )
            run.provider_config_id = actual_config_id
            existing_metadata = _metadata_dict(run.metadata_json)
            run.metadata_json = {
                **existing_metadata,
                "requested_provider": requested_provider_type,
                "actual_provider": run.provider_type,
                "requested_deployment_id": existing_metadata.get("deployment_id"),
                "deployment_id": str(spec.deployment_id) if spec.deployment_id else None,
            }
            limits = resolve_provider_limits(
                settings=self.settings,
                provider=provider,
                capabilities=getattr(spec, "capabilities", None) or {},
                model_id=run.model_name,
                provider_type=run.provider_type,
            )
            if not source_body(chunks).strip():
                raise AnalysisError(422, "ANALYSIS_SOURCE_CONTENT_EMPTY", "资料没有可分析的正文，未调用模型。")
            system = load_prompt("system.md")
            schema = load_schema()
            output_tokens = self._output_limit(chunks, provider, limits, system_prompt=system)
            compact_image_list = is_compact_image_list(source, document, chunks)
            if compact_image_list:
                system += ("\n\n" + load_prompt("compact_image_list.md"))
                # Use one adequately sized request; the previous 2k→6k repeated
                # reasoning sequence spent 8k output tokens without reaching JSON.
                output_tokens = min(limits.output_ceiling, max(output_tokens, self.settings.analysis_max_output_tokens))
            strategy, groups = self._plan(chunks, provider, limits, output_tokens)
            usage["input_chunk_count"] = len(chunks)
            usage["input_char_count"] = len(source_body(chunks))
            usage["budget_output_initial"] = output_tokens
            usage["analysis_mode"] = "COMPACT_IMAGE_LIST" if compact_image_list else "STANDARD"
            usage["context_window"] = limits.context_window
            usage["output_ceiling"] = limits.output_ceiling
            if limits.pricing_source:
                usage["model_pricing_hint"] = limits.pricing_source
            intermediates = []
            set_analysis_stage(self.session, run, STAGE_CALLING_MODEL)
            if strategy == "HIERARCHICAL":
                for group in groups:
                    parsed, _responses = self._complete(
                        provider,
                        system,
                        self._user(group, document.status, document.plain_text),
                        schema,
                        usage,
                        source.privacy_level,
                        output_tokens,
                        limits=limits,
                        compact_image_list=compact_image_list,
                    )
                    intermediates.append(parsed.model_dump())
                merge_user = self._merge_user(chunks, intermediates, document.status, document.plain_text, limits, output_tokens)
                parsed, responses = self._complete(
                    provider,
                    system,
                    merge_user,
                    schema,
                    usage,
                    source.privacy_level,
                    output_tokens,
                    limits=limits,
                    compact_image_list=compact_image_list,
                )
            else:
                parsed, responses = self._complete(
                    provider,
                    system,
                    self._user(chunks, document.status, document.plain_text),
                    schema,
                    usage,
                    source.privacy_level,
                    output_tokens,
                    limits=limits,
                    compact_image_list=compact_image_list,
                )
            set_analysis_stage(self.session, run, STAGE_VALIDATING)
            if run.status != "RUNNING":
                return run
            if not set_analysis_stage(self.session, run, STAGE_SAVING):
                return run
            issues = self._persist(run, parsed, chunks)
            run.analysis_strategy = strategy
            terminal_stage = STAGE_PARTIAL if issues else STAGE_SUCCEEDED
            run.metadata_json = {
                **_metadata_dict(run.metadata_json),
                "stage": terminal_stage,
                "stage_updated_at": datetime.now(timezone.utc).isoformat(),
                "strategy": strategy,
                "validation_issues": issues,
                "calls": usage["calls"],
                "output_strategy": usage.get("output_strategy"),
                "schema_notice": usage.get("schema_notice"),
                "finish_reason": usage.get("finish_reason"),
                "http_status": usage.get("http_status"),
                "response_id": usage.get("response_id"),
                "requested_provider": requested_provider_type,
                "actual_provider": usage.get("actual_provider"),
                "is_local": usage.get("is_local"),
                "input_chunk_count": usage.get("input_chunk_count"),
                "input_char_count": usage.get("input_char_count"),
                "analysis_mode": usage.get("analysis_mode"),
                "call_diagnostics": usage.get("call_diagnostics", []),
            }
            if usage.get("actual_provider"):
                run.provider_type = usage["actual_provider"]
            run.input_tokens = usage["input_tokens"] or None
            run.output_tokens = usage["output_tokens"] or None
            run.total_tokens = usage["total_tokens"] or None
            run.latency_ms = usage["latency_ms"]
            terminal_status = "PARTIAL" if issues else "SUCCEEDED"
            run.error_code = "EVIDENCE_VALIDATION_FAILED" if issues else None
            run.error_message = (f"分析结果存在 {len(issues)} 项证据校验问题。" if issues else None)
            run.completed_at = datetime.now(timezone.utc)
            self.session.flush()
            committed = self.session.execute(
                update(AnalysisRun)
                .where(AnalysisRun.id == run.id, AnalysisRun.status == "RUNNING")
                .values(status=terminal_status)
                .returning(AnalysisRun.id)
                .execution_options(synchronize_session=False)
            ).scalar_one_or_none()
            if committed is None:
                self.session.rollback()
                self.session.refresh(run)
                return run
            run.status = terminal_status
            self._mark_current(run)
            self.session.commit()
            self._organize(run)
            if run.status in {"SUCCEEDED", "PARTIAL"}:
                try:
                    from app.services.cover.auto import maybe_enqueue_auto_cover

                    maybe_enqueue_auto_cover(self.session, source.id)
                except Exception:
                    pass
        except AnalysisError as exc:
            self.session.rollback()
            run = self.session.get(AnalysisRun, run_id)
            if run is not None:
                self._fail(run, exc.code, exc.message, usage)
        except LLMError as exc:
            self.session.rollback()
            run = self.session.get(AnalysisRun, run_id)
            if run is not None:
                self._fail(run, exc.code, exc.message, usage)
        except Exception as exc:
            diagnostic = _safe_analysis_exception(exc, locals().get("provider"))
            self.session.rollback()
            run = self.session.get(AnalysisRun, run_id)
            if run is not None:
                run.metadata_json = {
                    **_metadata_dict(run.metadata_json),
                    "error_diagnostics": {
                        "exception_type": type(exc).__name__,
                        "traceback": diagnostic,
                    },
                }
                from app.core.logging import log_event

                log_event(
                    "analysis_unexpected_exception",
                    level=40,
                    run_id=str(run.id),
                    source_id=str(run.source_item_id),
                    job_type="analysis",
                    message=diagnostic,
                )
                self._fail(run, "PROVIDER_UNAVAILABLE", type(exc).__name__, usage)
        if run is None:
            raise AnalysisError(404, "ANALYSIS_NOT_FOUND", "找不到分析任务。")
        self.session.refresh(run)
        return run


    def view(self, source_id: uuid.UUID, run_id: uuid.UUID | None = None):
        source = self.session.get(SourceItem, source_id)
        if source is None:
            raise AnalysisError(404, "SOURCE_NOT_FOUND", "找不到该资料。")
        if run_id is None:
            latest = self.session.scalar(
                select(AnalysisRun).where(AnalysisRun.source_item_id == source_id).order_by(AnalysisRun.created_at.desc()).limit(1)
            )
            if latest is not None and latest.status in {"PENDING", "RUNNING"}:
                run = latest
            else:
                run = self.session.scalar(select(AnalysisRun).where(AnalysisRun.source_item_id == source_id, AnalysisRun.is_current.is_(True)))
                if run is None:
                    run = latest
        else:
            run = self.session.get(AnalysisRun, run_id)
            if run is None or run.source_item_id != source_id:
                raise AnalysisError(404, "ANALYSIS_NOT_FOUND", "找不到分析任务。")
        history = list(self.session.scalars(select(AnalysisRun).where(AnalysisRun.source_item_id == source_id).order_by(AnalysisRun.created_at.desc())).all())
        result = None
        claims = []
        evidence = []
        if run is not None:
            result = self.session.scalar(select(AnalysisResult).where(AnalysisResult.analysis_run_id == run.id))
            if result is not None:
                claims = list(self.session.scalars(select(Claim).where(Claim.analysis_result_id == result.id).order_by(Claim.sequence.asc())).all())
                if claims:
                    evidence = list(self.session.scalars(select(Evidence).where(Evidence.claim_id.in_([item.id for item in claims]))).all())
        configured = any(endpoint_configured(item, self.settings, self.session) for item in provider_specs(self.settings, self.session))
        return run, result, claims, evidence, history, configured

    def _call_provider(self, provider, request: LLMRequest) -> LLMResponse:
        from app.services.llm.provider_gate import provider_call_slot

        provider_type = getattr(provider, "provider_type", None) or "UNKNOWN"
        if provider_type == "FAKE" or getattr(provider, "is_local", False):
            return provider.complete(request)
        with provider_call_slot(provider_type, settings=self.settings):
            return provider.complete(request)

    def _complete(
        self,
        provider,
        system: str,
        user: str,
        schema: dict,
        usage: dict,
        privacy_level: str = "PUBLIC",
        max_output_tokens: int | None = None,
        *,
        limits: ProviderLimits | None = None,
        compact_image_list: bool = False,
    ) -> tuple[SourceAnalysis, list[LLMResponse]]:
        responses = []
        limits = limits or resolve_provider_limits(settings=self.settings, provider=provider)
        budget = max_output_tokens or self.settings.analysis_max_output_tokens
        budget = min(budget, limits.output_ceiling)
        request = LLMRequest(system, user, schema, 0, budget, {"purpose": "analysis"})
        self._assert_roles(system, user)
        requested = getattr(provider, "provider_type", None)
        try:
            response = self._call_provider(provider, request)
        except LLMError as exc:
            fallback = select_fallback(self.settings, requested or "", privacy_level) if exc.code in RETRYABLE else None
            if fallback is None:
                raise
            provider = self.providers.get(fallback.provider_type) or build_provider(fallback, self.settings, session=self.session)
            response = self._call_provider(provider, request)
        usage["requested_provider"] = requested
        usage["actual_provider"] = getattr(provider, "provider_type", requested)
        usage["is_local"] = bool(getattr(provider, "is_local", False))
        responses.append(response)
        self._add_usage(usage, response)
        self._record_call_diagnostics(usage, request, response)
        response = self._prefer_grounded_text(response)
        parsed, first_error = self._parse_response(response)
        if _needs_output_room(response, parsed) and user_has_source_text(user):
            if compact_image_list:
                raise AnalysisError(422, "ANALYSIS_OUTPUT_TRUNCATED", "截图分析在单次输出预算内被截断；未自动重复付费调用。")
            input_tokens = estimate_tokens(system) + estimate_tokens(user)
            retry_budget = raised_output_budget(
                initial=budget,
                context_window=limits.context_window,
                input_tokens=input_tokens,
                output_ceiling=limits.output_ceiling,
            )
            usage["budget_output_retry"] = retry_budget
            if retry_budget <= budget:
                raise AnalysisError(422, "ANALYSIS_OUTPUT_TRUNCATED", "模型输出已达到配置上限；未重复同预算请求。可手动重试或拆分资料后分析。")
            room = LLMRequest(system, user, schema, 0, retry_budget, {"purpose": "analysis"})
            retry = self._call_provider(provider, room)
            responses.append(retry)
            self._add_usage(usage, retry)
            self._record_call_diagnostics(usage, room, retry)
            response = self._prefer_grounded_text(retry)
            parsed, first_error = self._parse_response(response)
            if parsed is not None and semantic_empty_result(parsed):
                raise AnalysisError(422, "ANALYSIS_EMPTY_SEMANTIC_RESULT", "已有正文，但模型返回了无输入摘要。")
            if parsed is not None:
                return parsed, responses
            if _needs_output_room(response, parsed) or not (response.text or "").strip():
                raise AnalysisError(422, "ANALYSIS_OUTPUT_TRUNCATED", "模型思考占满了输出上限，没有返回可解析的分析结果。")
        if parsed is not None and semantic_empty_result(parsed) and user_has_source_text(user):
            retry = self._call_provider(provider, request)
            responses.append(retry)
            self._add_usage(usage, retry)
            self._record_call_diagnostics(usage, request, retry)
            try:
                retried = parse_analysis(retry.text)
            except ValueError as exc:
                if retry.finish_reason == "length":
                    raise AnalysisError(422, "ANALYSIS_OUTPUT_TRUNCATED", "语义恢复达到输出上限；已停止自动调用。") from exc
                raise AnalysisError(422, "STRUCTURED_OUTPUT_INVALID", "模型输出无法通过结构化校验。") from exc
            if semantic_empty_result(retried):
                raise AnalysisError(422, "ANALYSIS_EMPTY_SEMANTIC_RESULT", "已有正文，但模型返回了无输入摘要。")
            return retried, responses
        if parsed is not None:
            return parsed, responses
        repair_user = render_user(
            load_prompt("repair.md"),
            error=str(first_error)[:800],
            schema=json.dumps(schema, ensure_ascii=False),
            previous=response.text[:12000],
        )
        repair_tokens = repair_output_budget(
            analysis_budget=budget,
            previous_chars=len(response.text),
            context_window=limits.context_window,
            prompt_chars=len(repair_user),
            ceiling=limits.output_ceiling,
        )
        repair = LLMRequest(system, repair_user, schema, 0, repair_tokens, {"purpose": "repair"})
        second = self._call_provider(provider, repair)
        responses.append(second)
        self._add_usage(usage, second)
        self._record_call_diagnostics(usage, repair, second)
        try:
            repaired = parse_analysis(second.text)
        except ValueError as exc:
            if second.finish_reason == "length":
                raise AnalysisError(422, "ANALYSIS_OUTPUT_TRUNCATED", "结构化修复也达到输出上限；已停止自动调用。") from exc
            raise AnalysisError(422, "STRUCTURED_OUTPUT_INVALID", "模型输出无法通过结构化校验。") from exc
        if semantic_empty_result(repaired) and user_has_source_text(user):
            raise AnalysisError(422, "ANALYSIS_EMPTY_SEMANTIC_RESULT", "已有正文，但模型返回了无输入摘要。")
        return repaired, responses

    @staticmethod
    def _parse_response(response: LLMResponse) -> tuple[SourceAnalysis | None, ValueError | None]:
        try:
            return parse_analysis(response.text), None
        except ValueError as exc:
            return None, exc

    def _prefer_grounded_text(self, response: LLMResponse) -> LLMResponse:
        reasoning = (response.raw_response_metadata or {}).get("reasoning_content") or ""
        if not reasoning:
            return response
        try:
            visible = parse_analysis(response.text)
        except ValueError:
            visible = None
        if visible is not None and not semantic_empty_result(visible):
            return response
        try:
            hidden = parse_analysis(reasoning)
        except ValueError:
            return response
        if semantic_empty_result(hidden):
            return response
        response.text = reasoning
        return response

    def _persist(self, run: AnalysisRun, parsed: SourceAnalysis, chunks: list[ContentChunk]) -> list[str]:
        by_id = {str(chunk.id): chunk for chunk in chunks}
        issues: list[str] = []
        result = AnalysisResult(
            id=uuid.uuid4(),
            analysis_run_id=run.id,
            summary=parsed.summary,
            language=output_language("\n".join(chunk.content for chunk in chunks), self.settings.analysis_output_language),
            raw_structured_json=parsed.model_dump(),
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(result)
        self.session.flush()
        sequence = 0
        buckets = [
            ("FACT", parsed.facts, True),
            ("SOURCE_CLAIM", parsed.source_claims, True),
            ("INFERENCE", parsed.inferences, False),
            ("HYPOTHESIS", parsed.hypotheses, False),
        ]
        for claim_type, statements, require_evidence in buckets:
            for statement in statements:
                valid, rejected = self._valid_evidence(statement, by_id)
                if rejected:
                    issues.extend(rejected)
                if require_evidence and not valid:
                    issues.append(f"{claim_type} dropped without valid evidence")
                    continue
                claim = Claim(
                    id=uuid.uuid4(),
                    analysis_result_id=result.id,
                    claim_type=claim_type,
                    text=statement.text,
                    confidence=statement.confidence,
                    importance=statement.importance,
                    sequence=sequence,
                    created_at=datetime.now(timezone.utc),
                )
                sequence += 1
                self.session.add(claim)
                self.session.flush()
                for item, chunk, start, end in valid:
                    self.session.add(
                        Evidence(
                            id=uuid.uuid4(),
                            claim_id=claim.id,
                            content_chunk_id=chunk.id,
                            quote_text=item.quote,
                            start_offset=start,
                            end_offset=end,
                            page_number=(chunk.metadata_json or {}).get("page_number"),
                            created_at=datetime.now(timezone.utc),
                        )
                    )
        for claim_type, rows in (("UNKNOWN", parsed.unknowns), ("QUESTION", parsed.questions)):
            for text in rows:
                self.session.add(Claim(id=uuid.uuid4(), analysis_result_id=result.id, claim_type=claim_type, text=text, sequence=sequence, created_at=datetime.now(timezone.utc)))
                sequence += 1
        result.raw_structured_json = {**parsed.model_dump(), "validation_issues": issues}
        return issues

    def _valid_evidence(self, statement: Statement, by_id: dict):
        valid = []
        rejected = []
        for item in statement.evidence:
            chunk = by_id.get(item.chunk_id)
            if chunk is None:
                rejected.append("unknown chunk id")
                continue
            if len(item.quote) > self.settings.max_evidence_quote_chars:
                rejected.append("quote too long")
                continue
            haystack = _norm(chunk.content)
            needle = _norm(item.quote)
            if not needle or needle not in haystack:
                rejected.append("quote not in chunk")
                continue
            start = chunk.content.find(item.quote)
            end = start + len(item.quote) if start >= 0 else None
            valid.append((item, chunk, start if start >= 0 else None, end))
        return valid, rejected

    def _output_limit(self, chunks: list[ContentChunk], provider, limits: ProviderLimits, *, system_prompt: str) -> int:
        source_chars = sum(len(chunk.content or "") for chunk in chunks)
        template = load_prompt("user.md")
        from app.services.analysis.budget import analysis_output_budget as compute_analysis_output_budget

        prompt_tokens = estimate_tokens(system_prompt) + estimate_tokens(template) + estimate_tokens(source_body(chunks))
        return compute_analysis_output_budget(
            source_chars=source_chars,
            chunk_count=len(chunks),
            context_window=limits.context_window,
            prompt_tokens=prompt_tokens,
            ceiling=limits.output_ceiling,
        )

    def _context_window(self, provider) -> int:
        return resolve_provider_limits(settings=self.settings, provider=provider).context_window

    def _plan(self, chunks: list[ContentChunk], provider, limits: ProviderLimits, output_reserve: int):
        budget = chunk_groups_budget(limits.context_window, output_reserve)
        if budget < 200:
            raise AnalysisError(422, "CONTEXT_TOO_LARGE", "上下文预算不足。")
        groups: list[list[ContentChunk]] = []
        current: list[ContentChunk] = []
        size = 0
        for chunk in chunks:
            need = estimate_tokens(format_chunk(chunk))
            if current and size + need > budget:
                groups.append(current)
                current = []
                size = 0
            current.append(chunk)
            size += need
        if current:
            groups.append(current)
        if len(groups) <= 1:
            return "SINGLE_PASS", groups or [[]]
        return "HIERARCHICAL", groups

    @staticmethod
    def _compact_intermediate(data: dict) -> dict:
        def trim_statement(row: dict) -> dict:
            evidence = []
            for item in row.get("evidence") or []:
                if not isinstance(item, dict):
                    continue
                quote = str(item.get("quote") or "")
                if len(quote) > 240:
                    quote = quote[:237] + "..."
                evidence.append({"chunk_id": item.get("chunk_id"), "quote": quote})
            return {"text": str(row.get("text") or "")[:500], "evidence": evidence}

        summary = str(data.get("summary") or "")[:400]
        return {
            "summary": summary,
            "facts": [trim_statement(item) for item in (data.get("facts") or [])[:8]],
            "source_claims": [trim_statement(item) for item in (data.get("source_claims") or [])[:8]],
            "inferences": [{"text": str(item.get("text") or "")[:400]} for item in (data.get("inferences") or [])[:5] if isinstance(item, dict)],
            "unknowns": [str(item)[:200] for item in (data.get("unknowns") or [])[:5]],
            "questions": [str(item)[:200] for item in (data.get("questions") or [])[:5]],
        }

    def _merge_user(
        self,
        chunks: list[ContentChunk],
        intermediates: list[dict],
        extraction_status: str,
        plain: str,
        limits: ProviderLimits,
        output_tokens: int,
    ) -> str:
        compact = [self._compact_intermediate(item) for item in intermediates]
        char_limit = merge_payload_char_limit(limits.context_window, reserve_output_tokens=output_tokens)
        while compact:
            payload = json.dumps(compact, ensure_ascii=False)
            if len(payload) <= char_limit:
                break
            compact = compact[:-1]
        payload = json.dumps(compact, ensure_ascii=False) if compact else "[]"
        chunk_id_list = "\n".join(f"- {chunk.id}" for chunk in chunks)
        return render_user(
            load_prompt("merge.md"),
            output_language=output_language(plain, self.settings.analysis_output_language),
            extraction_status=extraction_status or "SUCCEEDED",
            chunk_id_list=chunk_id_list,
            intermediate_json=payload,
        )

    def _user(self, chunks: list[ContentChunk], extraction_status: str, plain: str) -> str:
        body = "\n".join(format_chunk(chunk) for chunk in chunks)
        return render_user(
            load_prompt("user.md"),
            output_language=output_language(plain, self.settings.analysis_output_language),
            extraction_status=extraction_status or "SUCCEEDED",
            source_content=body,
        )

    def _inputs(self, source_id: uuid.UUID):
        source = self.session.get(SourceItem, source_id)
        if source is None:
            raise AnalysisError(404, "SOURCE_NOT_FOUND", "找不到该资料。")
        extraction = self.session.scalar(select(ExtractionRun).where(ExtractionRun.source_item_id == source_id, ExtractionRun.is_current.is_(True)))
        if extraction is None or extraction.status not in {"SUCCEEDED", "PARTIAL"}:
            raise AnalysisError(409, "SOURCE_NOT_EXTRACTED", "资料还没有可分析的提取结果。")
        document = self.session.scalar(select(ExtractedDocument).where(ExtractedDocument.extraction_run_id == extraction.id))
        if document is None:
            raise AnalysisError(409, "SOURCE_NOT_EXTRACTED", "资料还没有可分析的提取结果。")
        if isinstance(document.metadata_json, dict) and document.metadata_json.get("content_completeness") == "metadata_only":
            raise AnalysisError(
                409,
                "SOURCE_CONTENT_INCOMPLETE",
                "X 页面目前只有元数据摘要，没有可验证的完整正文。请先补充原文后再分析。",
            )
        chunks = list(self.session.scalars(select(ContentChunk).where(ContentChunk.extracted_document_id == document.id).order_by(ContentChunk.sequence.asc())).all())
        return source, document, chunks, extraction.status

    def _select(self, provider_type: str | None) -> ProviderSpec:
        from app.services.llm.routing import RoutingError, resolve_workflow

        try:
            return resolve_workflow(self.session, self.settings, "ANALYSIS", provider_type)
        except RoutingError as exc:
            raise AnalysisError(409, exc.code, exc.message) from exc

    @staticmethod
    def _require_fake_scope(source: SourceItem, spec: ProviderSpec) -> None:
        if spec.provider_type == "FAKE" and source.system_scope != "AUTOMATION_TEST":
            raise AnalysisError(403, "FAKE_PROVIDER_FORBIDDEN", "Fake 模型仅可用于 AUTOMATION_TEST 资料。")

    def _check_privacy(self, source: SourceItem, spec: ProviderSpec) -> None:
        if (source.privacy_level or "PRIVATE") == "SENSITIVE" and not spec.is_local:
            raise AnalysisError(403, "PRIVACY_PROVIDER_NOT_ALLOWED", "敏感资料只能使用本机模型。")

    def _mark_current(self, run: AnalysisRun) -> None:
        if run.status not in {"SUCCEEDED", "PARTIAL"}:
            return
        newer_success = self.session.scalar(
            select(AnalysisRun.id).where(
                AnalysisRun.source_item_id == run.source_item_id,
                AnalysisRun.id != run.id,
                AnalysisRun.created_at > run.created_at,
                AnalysisRun.status.in_(("SUCCEEDED", "PARTIAL")),
            ).limit(1)
        )
        if newer_success is not None:
            run.is_current = False
            return
        self.session.execute(update(AnalysisRun).where(AnalysisRun.source_item_id == run.source_item_id, AnalysisRun.id != run.id).values(is_current=False))
        run.is_current = True

    def _result_id(self, run_id: uuid.UUID):
        return self.session.scalar(select(AnalysisResult.id).where(AnalysisResult.analysis_run_id == run_id))

    def _organize(self, run: AnalysisRun) -> None:
        if run.status not in {"SUCCEEDED", "PARTIAL"}:
            return
        try:
            from app.services.organization.service import OrganizationService

            OrganizationService(self.session, threshold=self.settings.category_assignment_threshold).organize(run.source_item_id)
        except Exception:
            # Analysis is already committed; organization is best-effort downstream.
            pass

    def _fail(self, run: AnalysisRun, code: str, message: str, usage: dict | None = None) -> AnalysisRun:
        failed = self.session.execute(
            update(AnalysisRun)
            .where(AnalysisRun.id == run.id, AnalysisRun.status.in_(("PENDING", "RUNNING")))
            .values(status="FAILED")
            .returning(AnalysisRun.id)
            .execution_options(synchronize_session=False)
        ).scalar_one_or_none()
        if failed is None:
            self.session.rollback()
            self.session.refresh(run)
            return run
        run.status = "FAILED"
        run.error_code = code
        run.error_message = message[:300]
        run.completed_at = datetime.now(timezone.utc)
        run.is_current = False
        meta = _metadata_dict(run.metadata_json)
        meta["stage"] = STAGE_FAILED
        meta["stage_updated_at"] = datetime.now(timezone.utc).isoformat()
        if usage and usage.get("calls"):
            run.input_tokens = usage["input_tokens"] or None
            run.output_tokens = usage["output_tokens"] or None
            run.total_tokens = usage["total_tokens"] or None
            run.latency_ms = usage["latency_ms"]
            meta.update(
                {
                    "calls": usage["calls"],
                    "output_strategy": usage.get("output_strategy"),
                    "schema_notice": usage.get("schema_notice"),
                    "finish_reason": usage.get("finish_reason"),
                    "http_status": usage.get("http_status"),
                    "response_id": usage.get("response_id"),
                    "requested_provider": usage.get("requested_provider"),
                    "actual_provider": usage.get("actual_provider"),
                    "is_local": usage.get("is_local"),
                    "analysis_mode": usage.get("analysis_mode"),
                    "call_diagnostics": usage.get("call_diagnostics", []),
                }
            )
            if usage.get("actual_provider"):
                run.provider_type = usage["actual_provider"]
        run.metadata_json = meta
        self.session.commit()
        self.session.refresh(run)
        return run

    @staticmethod
    def _add_usage(usage: dict, response: LLMResponse) -> None:
        usage["calls"] += 1
        usage["latency_ms"] += response.latency_ms or 0
        for key, value in (("input_tokens", response.input_tokens), ("output_tokens", response.output_tokens), ("total_tokens", response.total_tokens)):
            if value is not None:
                usage[key] += int(value)
        meta = response.raw_response_metadata or {}
        if meta.get("http_status") is not None:
            usage["http_status"] = meta.get("http_status")
        if meta.get("id"):
            usage["response_id"] = meta.get("id")
        if meta.get("strategy"):
            usage["output_strategy"] = meta.get("strategy")
        if meta.get("schema_notice"):
            usage["schema_notice"] = meta.get("schema_notice")
        if response.finish_reason:
            usage["finish_reason"] = response.finish_reason
        raw_usage = (response.raw_response_metadata or {}).get("usage_details")
        if isinstance(raw_usage, dict) and raw_usage.get("reasoning_tokens") is not None:
            usage["reasoning_tokens_observed"] = raw_usage.get("reasoning_tokens")

    @staticmethod
    def _record_call_diagnostics(usage: dict, request: LLMRequest, response: LLMResponse) -> None:
        """Persist bounded response diagnostics, never raw source, output, or chain-of-thought."""
        meta = response.raw_response_metadata or {}
        usage.setdefault("call_diagnostics", []).append(
            {
                "max_tokens": request.max_output_tokens,
                "reasoning_effort": (meta.get("request_parameters") or {}).get("reasoning_effort"),
                "request_parameters": meta.get("request_parameters"),
                "finish_reason": response.finish_reason,
                "http_status": meta.get("http_status"),
                "response_id": meta.get("id"),
                "content_chars": len(response.text or ""),
                "reasoning_content_present": bool(meta.get("reasoning_content_present")),
                "reasoning_content_chars": int(meta.get("reasoning_content_chars") or 0),
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "total_tokens": response.total_tokens,
                "reasoning_tokens": (meta.get("usage_details") or {}).get("reasoning_tokens"),
            }
        )

    @staticmethod
    def _assert_roles(system: str, user: str) -> None:
        if "<source_content>" in system:
            raise AnalysisError(500, "PROVIDER_UNAVAILABLE", "系统提示词不能包含资料正文。")
        if not user.strip().startswith("Output language:") and "<source_content>" not in user:
            raise AnalysisError(500, "PROVIDER_UNAVAILABLE", "资料必须放在用户消息中。")
