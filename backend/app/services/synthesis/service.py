import json
import logging
import time as time_module
import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT, Settings, get_settings
from app.models.analysis import AnalysisResult, AnalysisRun, Claim, Evidence
from app.models.discovery import OriginalSourceCandidate, SourceRelation
from app.models.extraction import ContentChunk, ExtractedDocument, ExtractionRun
from app.models.ingestion_record import IngestionRecord
from app.models.organization import Category, SourceCategoryAssignment, SourceTopicAssignment, Topic
from app.models.source_asset import SourceAsset
from app.models.source_item import SourceItem
from app.models.synthesis import Brief, BriefCitation, BriefSource, TopicSynthesis, TopicSynthesisCitation, TopicSynthesisSource
from app.services.analysis.schema import extract_json_object
from app.services.llm.fallback import RETRYABLE, select_fallback
from app.services.llm.provider import FakeLLMProvider
from app.services.llm.registry import build_provider
from app.services.llm.routing import RoutingError, resolve_workflow
from app.services.llm.types import LLMError, LLMRequest

PROMPT_VERSION = "1.1.0"
_BRIEF_SCHEMA_GUIDE = (
    "JSON keys: title, executive_summary, themes[{title, summary, points}], key_facts, agreements, "
    "disagreements, new_developments, knowledge_to_remember, open_questions, projects_or_tools. "
    "Each point is {text, statement_type, citations:[{source_id, claim_id, chunk_id, quote}]}."
)
logger = logging.getLogger(__name__)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
POINT_KEYS = (
    "themes",
    "key_facts",
    "agreements",
    "disagreements",
    "new_developments",
    "knowledge_to_remember",
    "open_questions",
    "projects_or_tools",
)
_CITATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "source_id": {"type": "string"},
        "claim_id": {"type": "string"},
        "chunk_id": {"type": "string"},
        "quote": {"type": "string"},
    },
    "required": ["source_id", "claim_id", "chunk_id", "quote"],
}
_POINT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "text": {"type": "string"},
        "statement_type": {
            "type": "string",
            "enum": ["FACT", "SOURCE_VIEW", "SYNTHESIS", "UNCERTAINTY", "AGREEMENT", "DISAGREEMENT"],
        },
        "citations": {"type": "array", "items": _CITATION_SCHEMA},
    },
    "required": ["text", "statement_type", "citations"],
}
_THEME_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "points": {"type": "array", "items": _POINT_SCHEMA},
    },
    "required": ["title", "summary", "points"],
}
SYNTHESIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "executive_summary": {"type": "string"},
        "themes": {"type": "array", "items": _THEME_SCHEMA},
        **{key: {"type": "array", "items": _POINT_SCHEMA} for key in POINT_KEYS if key != "themes"},
    },
    "required": ["title", "executive_summary", *POINT_KEYS],
}


class SynthesisService:
    def __init__(self, session: Session, settings: Settings | None = None, *, inline: bool = False, enqueue=None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.inline = inline
        self.enqueue = enqueue
        self.reduction_levels = 0

    def _creation_scope(self) -> str:
        from app.services.system_scope import creation_scope_from_settings

        return creation_scope_from_settings(self.settings)

    def preview(self, filters: dict) -> dict:
        rows = self._selection(filters)
        frozen = self._frozen_filters(filters)
        primaries = [row for row in rows if row["role"] == "PRIMARY_SELECTED"]
        included = [row for row in rows if row["included"]]
        funnel = self._brief_funnel_counts(primaries)
        stats = {
            "total_in_range": len(primaries),
            "included_for_brief": len(included),
            "excluded_count": len(primaries) - len([row for row in primaries if row["included"]]),
            "exclusion_reasons": self._reason_counts(rows),
            **funnel,
        }
        return {
            "filters": frozen,
            "sources": rows,
            "stats": stats,
            "diagnosis": self._brief_diagnosis(primaries, included),
            "llm_called": False,
        }

    def create_brief(self, filters: dict, provider_type: str | None = None, *, regenerated_from_id: uuid.UUID | None = None) -> Brief:
        frozen = self._frozen_filters(filters)
        now = datetime.now(timezone.utc)
        preview_rows = self._selection(filters)
        preview_included = [row for row in preview_rows if row["included"]]
        brief = Brief(
            id=uuid.uuid4(),
            title=None,
            start_date=frozen["start_date"],
            end_date=frozen["end_date"],
            date_basis=frozen["date_basis"],
            detail_level=frozen["detail_level"],
            status="PENDING",
            provider_type=provider_type,
            prompt_name=self._prompt_name(frozen),
            prompt_version=PROMPT_VERSION,
            filters_json={
                **frozen,
                "start_date": frozen["start_date"].isoformat(),
                "end_date": frozen["end_date"].isoformat(),
            },
            exclusion_reasons_json=self._reason_counts(preview_rows),
            structured_result_json={},
            selected_source_count=len(preview_rows),
            included_source_count=len(preview_included),
            excluded_source_count=len(preview_rows) - len(preview_included),
            created_at=now,
            regenerated_from_id=regenerated_from_id,
            system_scope=self._creation_scope(),
        )
        if not self.inline:
            brief.filters_json["rq_job_id"] = str(brief.id)
        self.session.add(brief)
        self.session.commit()
        if self.inline:
            return self.execute_brief(brief.id)
        if self.enqueue is not None:
            try:
                self.enqueue("brief", str(brief.id))
            except Exception as exc:
                logger.warning("brief enqueue failed (%s)", type(exc).__name__)
                self.session.rollback()
                current = self.session.get(Brief, brief.id)
                if current is not None and current.status == "PENDING":
                    return self._finish_brief(current, "FAILED", "QUEUE_ENQUEUE_FAILED", f"后台任务未能加入队列（{type(exc).__name__}）。")
                raise
        return brief

    def regenerate(self, brief_id: uuid.UUID) -> Brief:
        previous = self.session.get(Brief, brief_id)
        if previous is None:
            raise LookupError("BRIEF_NOT_FOUND")
        return self.create_brief(previous.filters_json, previous.provider_type, regenerated_from_id=previous.id)

    def execute_brief(self, brief_id: uuid.UUID) -> Brief:
        brief = self.session.scalar(select(Brief).where(Brief.id == brief_id).with_for_update())
        if brief is None:
            raise LookupError("BRIEF_NOT_FOUND")
        if brief.status != "PENDING":
            return brief
        brief.status = "RUNNING"
        brief.filters_json = {**(brief.filters_json or {}), "worker_started_at": datetime.now(timezone.utc).isoformat()}
        self.session.commit()
        rows = self._selection(brief.filters_json)
        self._store_brief_sources(brief, rows)
        included = [row for row in rows if row["included"]]
        primaries = [row for row in included if row["role"] == "PRIMARY_SELECTED"]
        brief.selected_source_count = len(rows)
        brief.included_source_count = len(included)
        brief.excluded_source_count = len(rows) - len(included)
        brief.source_count = len([row for row in rows if row["role"] == "PRIMARY_SELECTED"])
        brief.supporting_source_count = len([row for row in rows if row["role"] == "SUPPORTING_ORIGINAL"])
        brief.exclusion_reasons_json = self._reason_counts(rows)
        if not any(row["role"] == "PRIMARY_SELECTED" for row in rows):
            return self._finish_brief(
                brief,
                "NO_CONTENT",
                "BRIEF_NO_SOURCES_IN_RANGE",
                "所选日期与分类范围内没有任何收藏资料。",
            )
        if not primaries:
            return self._finish_brief(
                brief,
                "NO_CONTENT",
                "BRIEF_NO_ANALYZED_SOURCES",
                "范围内有资料，但尚未完成可用的 AI 分析，无法生成学习笔记。",
            )
        spec = self._spec(brief.provider_type)
        if spec is None:
            return self._finish_brief(brief, "FAILED", "PROVIDER_NOT_CONFIGURED", "没有已配置的模型提供方。")
        if any(row["privacy_level"] == "SENSITIVE" for row in primaries) and not spec.is_local:
            return self._finish_brief(brief, "FAILED", "BRIEF_PRIVACY_PROVIDER_NOT_ALLOWED", "所选资料含敏感内容，请改用本地模型或排除敏感资料。")
        packets = [self._packet(row["source_id"]) for row in included]
        packets = [item for item in packets if item["items"]]
        if not packets:
            return self._finish_brief(
                brief,
                "NO_CONTENT",
                "BRIEF_NO_CLAIMS",
                "资料已分析，但没有足够的已验证要点可用于生成学习笔记。",
            )
        try:
            sensitive = any(row["privacy_level"] == "SENSITIVE" for row in primaries)
            payload, usage = self._generate(spec, brief.prompt_name, brief.detail_level, packets, sensitive=sensitive)
        except LLMError as exc:
            self._store_failure_diagnostics(brief, spec, exc.diagnostics)
            return self._finish_brief(brief, "FAILED", exc.code, exc.message)
        except Exception as exc:
            logger.exception("brief generation failed")
            self.session.rollback()
            brief = self.session.get(Brief, brief_id)
            if brief is None or brief.status != "RUNNING":
                raise
            return self._finish_brief(brief, "FAILED", "JOB_FAILED", f"综合任务没有完成：{type(exc).__name__}"[:200])
        brief.provider_type = usage.get("actual_provider") or spec.provider_type
        brief.filters_json = {
            **brief.filters_json,
            "requested_provider": usage.get("requested_provider") or spec.provider_type,
            "actual_provider": brief.provider_type,
            "is_local": usage.get("is_local", spec.is_local),
            "output_strategy": usage.get("output_strategy"),
        }
        brief.model_name = usage["model"]
        brief.input_tokens = usage["input_tokens"]
        brief.output_tokens = usage["output_tokens"]
        brief.total_tokens = usage["total_tokens"]
        brief.latency_ms = usage["latency_ms"]
        brief.filters_json = {**(brief.filters_json or {}), "generation_diagnostics": self._safe_generation_diagnostics(usage)}
        validated, dropped = self._validate(payload, {row["source_id"] for row in included})
        if not self._has_points(validated):
            return self._finish_brief(brief, "FAILED", "CITATION_VALIDATION_FAILED", "没有通过校验的综合内容。")
        numbers = self._number_sources(validated)
        self._mark_uncited(brief, set(numbers))
        for row in self.session.scalars(select(BriefSource).where(BriefSource.brief_id == brief.id)):
            row.citation_number = numbers.get(row.source_item_id)
        self._store_citations(brief, validated, numbers)
        brief.structured_result_json = _jsonable(validated)
        brief.title = validated.get("title") or "学习摘要"
        brief.content_markdown = render_markdown(validated, self._source_index(numbers))
        status = "PARTIAL" if dropped or brief.excluded_source_count else "SUCCEEDED"
        return self._finish_brief(brief, status, "PARTIAL_CONTENT" if status == "PARTIAL" else None, None)

    def create_topic_synthesis(self, topic_id: uuid.UUID, provider_type: str | None = None, filters: dict | None = None) -> TopicSynthesis:
        topic = self._canonical_topic(topic_id)
        if topic is None:
            raise LookupError("TOPIC_NOT_FOUND")
        now = datetime.now(timezone.utc)
        row = TopicSynthesis(
            id=uuid.uuid4(),
            topic_id=topic.id,
            status="PENDING",
            provider_type=provider_type,
            prompt_name="topic-synthesis",
            prompt_version=PROMPT_VERSION,
            filters_json=filters or {},
            structured_result_json={},
            created_at=now,
        )
        self.session.add(row)
        self.session.commit()
        if self.inline:
            return self.execute_topic(row.id)
        if self.enqueue is not None:
            self.enqueue("topic", str(row.id))
        return row

    def execute_topic(self, synthesis_id: uuid.UUID) -> TopicSynthesis:
        row = self.session.get(TopicSynthesis, synthesis_id)
        if row is None:
            raise LookupError("SYNTHESIS_NOT_FOUND")
        row.status = "RUNNING"
        self.session.commit()
        topic_ids = self._topic_family(row.topic_id)
        assignments = list(
            self.session.scalars(
                select(SourceTopicAssignment).where(
                    SourceTopicAssignment.topic_id.in_(topic_ids),
                    SourceTopicAssignment.status == "ACTIVE",
                )
            )
        )
        seen = []
        for assignment in assignments:
            if assignment.source_item_id in seen:
                continue
            seen.append(assignment.source_item_id)
            ready, reason = self._ready(assignment.source_item_id)
            self.session.add(
                TopicSynthesisSource(
                    id=uuid.uuid4(),
                    synthesis_id=row.id,
                    source_item_id=assignment.source_item_id,
                    included=ready,
                    exclusion_reason=reason,
                    created_at=datetime.now(timezone.utc),
                )
            )
        self.session.flush()
        included_ids = [source_id for source_id in seen if self._ready(source_id)[0]]
        row.source_count = len(included_ids)
        if not included_ids:
            row.status = "NO_CONTENT"
            row.error_message = "该主题没有可综合的已分析资料。"
            row.completed_at = datetime.now(timezone.utc)
            self.session.commit()
            return row
        spec = self._spec(row.provider_type)
        if spec is None:
            row.status = "FAILED"
            row.error_code = "PROVIDER_NOT_CONFIGURED"
            row.completed_at = datetime.now(timezone.utc)
            self.session.commit()
            return row
        if any(self.session.get(SourceItem, source_id).privacy_level == "SENSITIVE" for source_id in included_ids) and not spec.is_local:
            row.status = "FAILED"
            row.error_code = "BRIEF_PRIVACY_PROVIDER_NOT_ALLOWED"
            row.completed_at = datetime.now(timezone.utc)
            self.session.commit()
            return row
        packets = [item for item in (self._packet(source_id) for source_id in included_ids) if item["items"]]
        try:
            sensitive = any(self.session.get(SourceItem, source_id).privacy_level == "SENSITIVE" for source_id in included_ids)
            payload, usage = self._generate(spec, "topic-synthesis", "STANDARD", packets, sensitive=sensitive)
        except LLMError as exc:
            row.status = "FAILED"
            row.error_code = exc.code
            row.error_message = exc.message
            row.completed_at = datetime.now(timezone.utc)
            self.session.commit()
            return row
        validated, dropped = self._validate(payload, set(included_ids))
        numbers = self._number_sources(validated)
        self._store_topic_citations(row, validated, numbers)
        row.structured_result_json = _jsonable(validated)
        row.provider_type = usage.get("actual_provider") or spec.provider_type
        row.filters_json = {
            **(row.filters_json or {}),
            "requested_provider": usage.get("requested_provider") or spec.provider_type,
            "actual_provider": row.provider_type,
            "is_local": usage.get("is_local", spec.is_local),
            "output_strategy": usage.get("output_strategy"),
        }
        row.model_name = usage["model"]
        row.input_tokens = usage["input_tokens"]
        row.output_tokens = usage["output_tokens"]
        row.total_tokens = usage["total_tokens"]
        row.latency_ms = usage["latency_ms"]
        row.content_markdown = render_markdown(validated, self._source_index(numbers))
        row.status = "PARTIAL" if dropped else "SUCCEEDED"
        row.completed_at = datetime.now(timezone.utc)
        self.session.commit()
        return row

    def _selection(self, filters: dict) -> list[dict]:
        frozen = self._frozen_filters(filters)
        from app.services.synthesis.date_bounds import calendar_range_utc

        start, end = calendar_range_utc(frozen["start_date"], frozen["end_date"], self.settings)
        records = list(
            self.session.scalars(
                select(IngestionRecord).where(
                    IngestionRecord.origin == "USER_COLLECTION",
                    IngestionRecord.status == "STORED",
                    IngestionRecord.source_item_id.is_not(None),
                )
            )
        )
        grouped: dict[uuid.UUID, list[IngestionRecord]] = {}
        for record in records:
            if frozen["date_basis"] == "COLLECTED_AT" and not (start <= record.collected_at < end):
                continue
            source = self.session.get(SourceItem, record.source_item_id)
            if source is None:
                continue
            if source.deleted_at is not None:
                continue
            from app.services.system_scope import scope_visible_for_api

            if not scope_visible_for_api(source.system_scope, self.settings):
                continue
            if frozen["date_basis"] == "PUBLISHED_AT":
                published = self._published_at(source.id)
                if published is None or not (start <= published < end):
                    continue
            if not self._matches_taxonomy(source.id, frozen):
                continue
            grouped.setdefault(source.id, []).append(record)
        rows = []
        for source_id, group in grouped.items():
            source = self.session.get(SourceItem, source_id)
            ready, reason = self._ready(source_id)
            rows.append(self._row(source, "PRIMARY_SELECTED", "USER_COLLECTION", ready, reason, group))
            for relation in self.session.scalars(
                select(SourceRelation).where(SourceRelation.from_source_id == source_id, SourceRelation.relation_type == "RESOLVES_TO")
            ):
                if relation.to_source_id in grouped or any(item["source_id"] == relation.to_source_id for item in rows):
                    continue
                supporting = self.session.get(SourceItem, relation.to_source_id)
                if supporting is None:
                    continue
                ready, reason = self._ready(supporting.id)
                rows.append(self._row(supporting, "SUPPORTING_ORIGINAL", "SOURCE_RELATION", ready, reason, []))
        return rows

    def _row(self, source: SourceItem, role: str, reason: str, ready: bool, exclusion: str | None, records: list[IngestionRecord]) -> dict:
        return {
            "source_id": source.id,
            "role": role,
            "selection_reason": reason,
            "included": ready,
            "exclusion_reason": None if ready else exclusion,
            "collection_count": len(records),
            "collection_record_id": None if not records else records[0].id,
            "title": source.display_name or "Untitled Source",
            "privacy_level": source.privacy_level,
            "original_url": source.original_url,
            "canonical_url": source.canonical_url,
        }

    def _matches_taxonomy(self, source_id: uuid.UUID, filters: dict) -> bool:
        slugs = filters.get("category_slugs") or []
        if slugs:
            assigned = set(
                self.session.scalars(
                    select(Category.slug)
                    .join(SourceCategoryAssignment, SourceCategoryAssignment.category_id == Category.id)
                    .where(SourceCategoryAssignment.source_item_id == source_id, SourceCategoryAssignment.status == "ACTIVE", Category.is_active.is_(True))
                )
            )
            if not assigned.intersection(slugs):
                return False
        topic_ids = filters.get("topic_ids") or []
        if topic_ids:
            allowed = set()
            for topic_id in topic_ids:
                topic = self._canonical_topic(uuid.UUID(str(topic_id)))
                if topic is not None:
                    allowed.update(self._topic_family(topic.id))
            hit = self.session.scalar(
                select(SourceTopicAssignment.id).where(
                    SourceTopicAssignment.source_item_id == source_id,
                    SourceTopicAssignment.status == "ACTIVE",
                    SourceTopicAssignment.topic_id.in_(allowed or [uuid.uuid4()]),
                )
            )
            if hit is None:
                return False
        return True

    def _extraction_ready(self, source_id: uuid.UUID) -> tuple[bool, str | None]:
        extraction = self.session.scalar(select(ExtractionRun).where(ExtractionRun.source_item_id == source_id, ExtractionRun.is_current.is_(True)))
        if extraction is None or extraction.status not in {"SUCCEEDED", "PARTIAL"}:
            return False, "EXTRACTION_FAILED" if extraction is not None else "NO_CURRENT_DOCUMENT"
        return True, None

    def _ready(self, source_id: uuid.UUID) -> tuple[bool, str | None]:
        ok, reason = self._extraction_ready(source_id)
        if not ok:
            return False, reason
        analysis = self.session.scalar(select(AnalysisRun).where(AnalysisRun.source_item_id == source_id, AnalysisRun.is_current.is_(True)))
        if analysis is None or analysis.status not in {"SUCCEEDED", "PARTIAL"}:
            return False, "NO_ANALYSIS"
        source = self.session.get(SourceItem, source_id)
        if source is not None and source.system_scope == "USER" and (analysis.provider_type == "FAKE" or analysis.model_name == "fake-model"):
            return False, "UNTRUSTED_FAKE_ANALYSIS"
        return True, None

    def _has_claims(self, source_id: uuid.UUID) -> bool:
        analysis = self.session.scalar(select(AnalysisRun).where(AnalysisRun.source_item_id == source_id, AnalysisRun.is_current.is_(True)))
        if analysis is None:
            return False
        source = self.session.get(SourceItem, source_id)
        if source is not None and source.system_scope == "USER" and (analysis.provider_type == "FAKE" or analysis.model_name == "fake-model"):
            return False
        result = self.session.scalar(select(AnalysisResult).where(AnalysisResult.analysis_run_id == analysis.id))
        if result is None:
            return False
        claim = self.session.scalar(select(Claim.id).where(Claim.analysis_result_id == result.id).limit(1))
        if claim is None:
            return False
        return self.session.scalar(select(Evidence.id).join(Claim, Evidence.claim_id == Claim.id).where(Claim.analysis_result_id == result.id).limit(1)) is not None

    def _brief_funnel_counts(self, primaries: list[dict]) -> dict:
        extraction_ok = 0
        analysis_ok = 0
        claims_ok = 0
        for row in primaries:
            sid = row["source_id"]
            if self._extraction_ready(sid)[0]:
                extraction_ok += 1
            if self._ready(sid)[0]:
                analysis_ok += 1
            if self._has_claims(sid):
                claims_ok += 1
        return {
            "extraction_ready_count": extraction_ok,
            "analysis_ready_count": analysis_ok,
            "claims_ready_count": claims_ok,
        }

    def _packet(self, source_id: uuid.UUID) -> dict:
        source = self.session.get(SourceItem, source_id)
        analysis = self.session.scalar(select(AnalysisRun).where(AnalysisRun.source_item_id == source_id, AnalysisRun.is_current.is_(True)))
        if source is not None and source.system_scope == "USER" and analysis is not None and (analysis.provider_type == "FAKE" or analysis.model_name == "fake-model"):
            analysis = None
        result = None if analysis is None else self.session.scalar(select(AnalysisResult).where(AnalysisResult.analysis_run_id == analysis.id))
        items = []
        if result is not None:
            claims = list(self.session.scalars(select(Claim).where(Claim.analysis_result_id == result.id).order_by(Claim.importance.desc(), Claim.sequence)))
            for claim in claims:
                evidence = self.session.scalar(select(Evidence).where(Evidence.claim_id == claim.id))
                if evidence is None:
                    continue
                chunk = self.session.get(ContentChunk, evidence.content_chunk_id)
                items.append(
                    {
                        "claim_id": claim.id,
                        "claim_type": claim.claim_type,
                        "text": claim.text,
                        "chunk_id": evidence.content_chunk_id,
                        "quote": evidence.quote_text or ("" if chunk is None else chunk.content[:180]),
                        "importance": claim.importance or 0,
                    }
                )
        topics = list(
            self.session.scalars(
                select(Topic.name)
                .join(SourceTopicAssignment, SourceTopicAssignment.topic_id == Topic.id)
                .where(SourceTopicAssignment.source_item_id == source_id, SourceTopicAssignment.status == "ACTIVE", Topic.merged_into_topic_id.is_(None))
            )
        )
        return {"source_id": source_id, "title": None if source is None else source.display_name, "summary": None if result is None else result.summary, "topics": topics or ["Uncategorized"], "items": items}

    def fits_context(self, request: LLMRequest) -> bool:
        overhead = 250
        tokens = _estimate_tokens(request.system_prompt) + _estimate_tokens(request.user_content) + request.max_output_tokens + overhead
        return tokens <= self._context_limit()

    def _context_limit(self) -> int:
        return getattr(self, "_active_context_window", None) or self.settings.default_llm_context_window

    def _bind_context_window(self, provider, spec) -> None:
        reported = int(getattr(provider, "context_window", 0) or 0)
        if not reported:
            reported = int((getattr(spec, "capabilities", None) or {}).get("context_window") or 0)
        self._active_context_window = max(self.settings.default_llm_context_window, reported)
        if self._active_context_window > self.settings.default_llm_context_window:
            current = float(getattr(provider, "timeout", 0) or 0)
            if current and current < 420:
                provider.timeout = 420

    def _output_budget(self) -> int:
        ceiling = self.settings.analysis_max_output_tokens
        if self._context_limit() <= self.settings.default_llm_context_window:
            return ceiling
        return min(8000, max(ceiling, self._context_limit() // 4))

    def _generate(self, spec, prompt_name: str, detail: str, packets: list[dict], *, sensitive: bool = False) -> tuple[dict, dict]:
        template = {
            "brief-knowledge": "knowledge",
            "brief-business": "business",
            "brief-project": "project",
            "brief-other": "other",
            "brief-general": "general",
            "topic-synthesis": "topic",
        }.get(prompt_name, "general")
        guidance = (PROJECT_ROOT / "prompts" / "synthesis" / "v1" / "templates" / f"{template}.md").read_text(encoding="utf-8")
        system = (PROJECT_ROOT / "prompts" / "synthesis" / "v1" / "system.md").read_text(encoding="utf-8")
        user_template = (PROJECT_ROOT / "prompts" / "synthesis" / "v1" / "user.md").read_text(encoding="utf-8")
        provider = FakeLLMProvider() if spec.provider_type == "FAKE" else build_provider(spec, self.settings, session=self.session)
        actual_spec = spec
        self._bind_context_window(provider, actual_spec)
        call_budget_seconds = max(int(self.settings.llm_timeout_seconds) * 3, 600) - 60
        deadline = time_module.monotonic() + call_budget_seconds

        usage = {
            "model": spec.model,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "latency_ms": 0,
            "request_count": 0,
            "attempts": [],
            "reduction_levels": 0,
            "requested_provider": spec.provider_type,
            "actual_provider": spec.provider_type,
        }

        def invoke(request: LLMRequest):
            nonlocal provider, actual_spec
            remaining = deadline - time_module.monotonic()
            if remaining <= 0:
                raise LLMError("SYNTHESIS_TIME_BUDGET_EXCEEDED", "笔记生成已达到本次任务的时间上限。", diagnostics=usage)
            provider_timeout = getattr(provider, "timeout", None)
            if provider_timeout is not None:
                provider.timeout = min(float(provider_timeout), remaining)
            request_started = time_module.monotonic()
            try:
                response = provider.complete(request)
            except LLMError as exc:
                usage["request_count"] += 1
                usage["latency_ms"] += int((time_module.monotonic() - request_started) * 1000)
                usage["attempts"].append({
                    "provider": actual_spec.provider_type,
                    "model": actual_spec.model,
                    "error_code": exc.code,
                    "error_type": type(exc).__name__,
                    "latency_ms": int((time_module.monotonic() - request_started) * 1000),
                    "max_tokens": request.max_output_tokens,
                    "purpose": request.metadata.get("purpose"),
                })
                fallback = select_fallback(self.settings, actual_spec.provider_type, "SENSITIVE" if sensitive else "PUBLIC") if exc.code in RETRYABLE else None
                if fallback is None:
                    exc.diagnostics = self._safe_generation_diagnostics(usage)
                    raise
                provider = build_provider(fallback, self.settings, session=self.session)
                actual_spec = fallback
                self._bind_context_window(provider, actual_spec)
                remaining = deadline - time_module.monotonic()
                if remaining <= 0:
                    raise LLMError("SYNTHESIS_TIME_BUDGET_EXCEEDED", "笔记生成已达到本次任务的时间上限。", diagnostics=usage) from exc
                fallback_timeout = getattr(provider, "timeout", None)
                if fallback_timeout is not None:
                    provider.timeout = min(float(fallback_timeout), remaining)
                request_started = time_module.monotonic()
                try:
                    response = provider.complete(request)
                except LLMError as fallback_error:
                    usage["request_count"] += 1
                    usage["latency_ms"] += int((time_module.monotonic() - request_started) * 1000)
                    usage["attempts"].append({
                        "provider": actual_spec.provider_type,
                        "model": actual_spec.model,
                        "error_code": fallback_error.code,
                        "error_type": type(fallback_error).__name__,
                        "latency_ms": int((time_module.monotonic() - request_started) * 1000),
                        "max_tokens": request.max_output_tokens,
                        "purpose": request.metadata.get("purpose"),
                    })
                    fallback_error.diagnostics = self._safe_generation_diagnostics(usage)
                    raise
            self._add_usage(usage, response)
            attempt = response.raw_response_metadata or {}
            request_parameters = attempt.get("request_parameters") if isinstance(attempt.get("request_parameters"), dict) else {}
            usage["attempts"].append({
                "provider": response.provider,
                "model": response.model,
                "http_status": attempt.get("http_status"),
                "response_id": attempt.get("id"),
                "strategy": attempt.get("strategy"),
                "finish_reason": response.finish_reason,
                "max_tokens": request.max_output_tokens,
                "purpose": request.metadata.get("purpose"),
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "total_tokens": response.total_tokens,
                "latency_ms": response.latency_ms,
                "reasoning_content_present": attempt.get("reasoning_content_present"),
                "reasoning_content_chars": attempt.get("reasoning_content_chars"),
                "request_parameters": {key: request_parameters.get(key) for key in ("endpoint", "model", "max_tokens", "thinking", "reasoning_effort", "response_format", "stream") if key in request_parameters},
            })
            usage["model"] = response.model
            usage["actual_provider"] = actual_spec.provider_type
            usage["is_local"] = actual_spec.is_local
            usage["output_strategy"] = attempt.get("strategy")
            return response
        current = packets
        depth = 0
        while True:
            groups = self._pack(system, user_template, template, guidance, detail, current, "final" if depth == 0 else "reduce")
            if len(groups) <= 1:
                ready = groups[0] if groups else current
                request = self._request(system, user_template, template, guidance, detail, ready, "final")
                if not self.fits_context(request):
                    raise LLMError("SYNTHESIS_CONTEXT_LIMIT_EXCEEDED", "综合内容超过上下文预算。")
                response = invoke(request)
                usage["reduction_levels"] = depth
                self.reduction_levels = depth
                try:
                    return extract_json_object(response.text), usage
                except ValueError as exc:
                    repair = LLMRequest(
                        system_prompt=system,
                        user_content=response.text + "\nReturn valid JSON only.",
                        response_schema=SYNTHESIS_SCHEMA,
                        temperature=0,
                        max_output_tokens=self._output_budget(),
                        metadata={"purpose": "brief", "schema_name": "brief_synthesis"},
                    )
                    if not self.fits_context(repair):
                        raise LLMError("SYNTHESIS_CONTEXT_LIMIT_EXCEEDED", "修复请求超过上下文预算。") from exc
                    repaired = invoke(repair)
                    try:
                        return extract_json_object(repaired.text), usage
                    except ValueError as repair_error:
                        raise LLMError("STRUCTURED_OUTPUT_INVALID", "模型没有返回可校验的 JSON。", diagnostics=self._safe_generation_diagnostics(usage)) from repair_error
            if depth >= 6:
                raise LLMError("SYNTHESIS_CONTEXT_LIMIT_EXCEEDED", "分层综合仍无法落入上下文预算。")
            reduced = []
            before = self._evidence_size(current)
            for group in groups:
                request = self._request(system, user_template, template, guidance, detail, group, "reduce")
                if not self.fits_context(request):
                    raise LLMError("SYNTHESIS_CONTEXT_LIMIT_EXCEEDED", "分批综合超过上下文预算。")
                response = invoke(request)
                reduced.append(self._intermediate_packet(group, response.text))
            fits_next = self._fits_packets(system, user_template, template, guidance, detail, reduced, "final")
            if not fits_next and self._evidence_size(reduced) >= before:
                raise LLMError("SYNTHESIS_CONTEXT_LIMIT_EXCEEDED", "分层综合无法继续压缩。")
            current = reduced
            depth += 1

    def _pack(self, system: str, user_template: str, template: str, guidance: str, detail: str, packets: list[dict], stage: str) -> list[list[dict]]:
        units: list[dict] = []
        for packet in packets:
            if self._fits_packets(system, user_template, template, guidance, detail, [packet], stage):
                units.append(packet)
            else:
                units.extend(self._split_packet(system, user_template, template, guidance, detail, packet))
        cap = max(1, self.settings.synthesis_batch_size)
        if self._fits_packets(system, user_template, template, guidance, detail, units, "final"):
            return [units]
        groups: list[list[dict]] = []
        current: list[dict] = []
        for unit in units:
            trial = current + [unit]
            over_cap = len(trial) > cap
            if current and (over_cap or not self._fits_packets(system, user_template, template, guidance, detail, trial, "reduce")):
                groups.append(current)
                current = [unit]
            else:
                current = trial
        if current:
            groups.append(current)
        return groups

    def _split_packet(self, system: str, user_template: str, template: str, guidance: str, detail: str, packet: dict) -> list[dict]:
        pieces: list[dict] = []
        current: list[dict] = []
        for item in packet.get("items") or []:
            fitted = item if self._fits_packets(system, user_template, template, guidance, detail, [{**packet, "items": [item]}], "reduce") else self._shrink_item(system, user_template, template, guidance, detail, packet, item)
            trial = {**packet, "items": current + [fitted]}
            if current and not self._fits_packets(system, user_template, template, guidance, detail, [trial], "reduce"):
                pieces.append({**packet, "items": current})
                current = [fitted]
            else:
                current = current + [fitted]
        if current:
            pieces.append({**packet, "items": current})
        if not pieces:
            raise LLMError("SYNTHESIS_CONTEXT_LIMIT_EXCEEDED", "空证据包超过上下文预算。")
        return pieces

    def _shrink_item(self, system: str, user_template: str, template: str, guidance: str, detail: str, packet: dict, item: dict) -> dict:
        quote = str(item.get("quote") or "")
        best = -1
        low = 0
        high = len(quote)
        while low <= high:
            mid = (low + high) // 2
            candidate = {**item, "quote": quote[:mid]}
            if self._fits_packets(system, user_template, template, guidance, detail, [{**packet, "items": [candidate]}], "reduce"):
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        if best < 0:
            raise LLMError("SYNTHESIS_CONTEXT_LIMIT_EXCEEDED", "单条证据超过上下文预算，无法继续综合。")
        return {**item, "quote": quote[:best]}

    def _fits_packets(self, system: str, user_template: str, template: str, guidance: str, detail: str, packets: list[dict], stage: str) -> bool:
        return self.fits_context(self._request(system, user_template, template, guidance, detail, packets, stage))

    def _intermediate_packet(self, group: list[dict], response_text: str) -> dict:
        summary = "批次综合"
        try:
            payload = extract_json_object(response_text)
            summary = str(payload.get("executive_summary") or summary)[:240]
        except ValueError:
            summary = "批次综合"
        items = []
        for packet in group:
            for item in packet.get("items") or []:
                items.append(
                    {
                        "source_id": item.get("source_id") or packet.get("source_id"),
                        "claim_id": item["claim_id"],
                        "claim_type": item["claim_type"],
                        "text": summary,
                        "chunk_id": item["chunk_id"],
                        "quote": str(item.get("quote") or "")[:80],
                        "importance": item.get("importance") or 0,
                    }
                )
        return {
            "kind": "intermediate",
            "source_id": items[0]["source_id"] if items else None,
            "title": "Intermediate synthesis",
            "topics": ["Reduction"],
            "summary": summary,
            "items": items,
        }

    def _evidence_size(self, packets: list[dict]) -> int:
        return len("\n".join(self._evidence_lines(packets)))

    def _evidence_lines(self, packets: list[dict]) -> list[str]:
        evidence = []
        for packet in packets:
            topics = ",".join(packet.get("topics") or [])
            evidence.append(f"[SOURCE id={packet.get('source_id')} title={packet.get('title')} topics={topics}]")
            if packet.get("kind") == "intermediate":
                evidence.append("Intermediate synthesis packet. These statements are run-local notes, not sources or claims. ITEM ids still point at original claims.")
            if packet.get("summary"):
                evidence.append(f"Summary: {packet['summary']}")
            for item in packet.get("items") or []:
                source_id = item.get("source_id") or packet.get("source_id")
                evidence.append(
                    f"[ITEM source_id={source_id} claim_id={item['claim_id']} chunk_id={item['chunk_id']} type={item['claim_type']}] {item.get('quote') or ''}"
                )
        return evidence

    def _request(self, system: str, user_template: str, template: str, guidance: str, detail: str, packets: list[dict], stage: str) -> LLMRequest:
        user = (
            user_template.replace("{{template}}", template)
            .replace("{{detail}}", detail)
            .replace("{{stage}}", stage)
            .replace("{{template_guidance}}", guidance)
            .replace("{{evidence}}", "\n".join(self._evidence_lines(packets)))
        )
        # JSON_OBJECT transports do not receive response_schema. Keep the contract visible without
        # crowding a small context window; large windows can carry the schema itself.
        if self._context_limit() >= 32000:
            user = user + "\n\nJSON schema:\n" + json.dumps(SYNTHESIS_SCHEMA, ensure_ascii=False)
        else:
            user = user + "\n\n" + _BRIEF_SCHEMA_GUIDE
        return LLMRequest(
            system_prompt=system,
            user_content=user,
            response_schema=SYNTHESIS_SCHEMA,
            temperature=0,
            max_output_tokens=self._output_budget(),
            metadata={"purpose": "brief", "schema_name": "brief_synthesis"},
        )

    def _validate(self, payload: dict, allowed_sources: set[uuid.UUID]) -> tuple[dict, bool]:
        dropped = False
        cleaned = {
            "title": str(payload.get("title") or "学习摘要"),
            "executive_summary": str(payload.get("executive_summary") or ""),
            "themes": [],
        }
        for key in POINT_KEYS:
            if key != "themes":
                cleaned[key] = []
        for theme in payload.get("themes") or []:
            points, theme_dropped = self._clean_points(theme.get("points") or [], allowed_sources)
            dropped = dropped or theme_dropped
            if points:
                cleaned["themes"].append({"title": str(theme.get("title") or "Theme"), "summary": str(theme.get("summary") or ""), "points": points})
        for key in POINT_KEYS:
            if key == "themes":
                continue
            points, key_dropped = self._clean_points(payload.get(key) or [], allowed_sources)
            cleaned[key] = points
            dropped = dropped or key_dropped
        return cleaned, dropped

    def _clean_points(self, points: list, allowed_sources: set[uuid.UUID]) -> tuple[list[dict], bool]:
        kept = []
        dropped = False
        for point in points:
            citations = []
            for citation in point.get("citations") or []:
                checked = self._check_citation(citation, allowed_sources)
                if checked is None:
                    dropped = True
                    continue
                citations.append(checked)
            statement = str(point.get("statement_type") or "SYNTHESIS")
            if statement not in {"FACT", "SOURCE_VIEW", "SYNTHESIS", "UNCERTAINTY", "AGREEMENT", "DISAGREEMENT"}:
                statement = "SYNTHESIS"
            cited_types = {item["claim_type"] for item in citations}
            if statement == "FACT" and cited_types != {"FACT"}:
                statement = "SOURCE_VIEW" if cited_types <= {"FACT", "SOURCE_CLAIM"} else "SYNTHESIS"
            if not citations:
                dropped = True
                continue
            kept.append({"text": str(point.get("text") or ""), "statement_type": statement, "citations": citations})
        return kept, dropped

    def _check_citation(self, citation: dict, allowed_sources: set[uuid.UUID]) -> dict | None:
        try:
            source_id = uuid.UUID(str(citation.get("source_id")))
            claim_id = uuid.UUID(str(citation.get("claim_id")))
            chunk_id = uuid.UUID(str(citation.get("chunk_id")))
        except (TypeError, ValueError):
            return None
        if source_id not in allowed_sources:
            return None
        claim = self.session.get(Claim, claim_id)
        evidence = None if claim is None else self.session.scalar(select(Evidence).where(Evidence.claim_id == claim.id, Evidence.content_chunk_id == chunk_id))
        chunk = self.session.get(ContentChunk, chunk_id)
        if claim is None or evidence is None or chunk is None:
            return None
        result = self.session.get(AnalysisResult, claim.analysis_result_id)
        run = None if result is None else self.session.get(AnalysisRun, result.analysis_run_id)
        document = self.session.get(ExtractedDocument, chunk.extracted_document_id)
        if run is None or document is None or run.source_item_id != source_id or document.source_item_id != source_id:
            return None
        quote = str(citation.get("quote") or "")
        cited = " ".join(quote.split())
        evidence_quote = " ".join((evidence.quote_text or "").split())
        chunk_text = " ".join(chunk.content.split())
        if not cited or not evidence_quote or cited not in evidence_quote or cited not in chunk_text:
            return None
        return {"source_id": source_id, "claim_id": claim.id, "chunk_id": chunk.id, "quote": quote, "claim_type": claim.claim_type}

    def _number_sources(self, payload: dict) -> dict[uuid.UUID, int]:
        numbers = {}
        for point in self._iter_points(payload):
            for citation in point["citations"]:
                source_id = citation["source_id"]
                if source_id not in numbers:
                    numbers[source_id] = len(numbers) + 1
                citation["citation_number"] = numbers[source_id]
        return numbers

    def _iter_points(self, payload: dict):
        for theme in payload.get("themes") or []:
            yield from theme.get("points") or []
        for key in POINT_KEYS:
            if key != "themes":
                yield from payload.get(key) or []

    def _has_points(self, payload: dict) -> bool:
        return any(True for _ in self._iter_points(payload))

    def _store_brief_sources(self, brief: Brief, rows: list[dict]) -> None:
        for row in rows:
            self.session.add(
                BriefSource(
                    id=uuid.uuid4(),
                    brief_id=brief.id,
                    source_item_id=row["source_id"],
                    selection_reason=row["selection_reason"],
                    collection_record_id=row["collection_record_id"],
                    role=row["role"],
                    included=row["included"],
                    exclusion_reason=row["exclusion_reason"],
                    collection_count=row["collection_count"],
                    created_at=datetime.now(timezone.utc),
                )
            )
        self.session.flush()

    def _store_citations(self, brief: Brief, payload: dict, numbers: dict[uuid.UUID, int]) -> None:
        seen = set()
        for point in self._iter_points(payload):
            for citation in point["citations"]:
                key = (citation["source_id"], citation["claim_id"], citation["chunk_id"])
                if key in seen:
                    continue
                seen.add(key)
                self.session.add(
                    BriefCitation(
                        id=uuid.uuid4(),
                        brief_id=brief.id,
                        citation_number=numbers[citation["source_id"]],
                        source_item_id=citation["source_id"],
                        claim_id=citation["claim_id"],
                        content_chunk_id=citation["chunk_id"],
                        quote_text=citation["quote"],
                        created_at=datetime.now(timezone.utc),
                    )
                )

    def _store_topic_citations(self, row: TopicSynthesis, payload: dict, numbers: dict[uuid.UUID, int]) -> None:
        seen = set()
        for point in self._iter_points(payload):
            for citation in point["citations"]:
                key = (citation["source_id"], citation["claim_id"], citation["chunk_id"])
                if key in seen:
                    continue
                seen.add(key)
                self.session.add(
                    TopicSynthesisCitation(
                        id=uuid.uuid4(),
                        synthesis_id=row.id,
                        citation_number=numbers[citation["source_id"]],
                        source_item_id=citation["source_id"],
                        claim_id=citation["claim_id"],
                        content_chunk_id=citation["chunk_id"],
                        quote_text=citation["quote"],
                        created_at=datetime.now(timezone.utc),
                    )
                )

    def _source_index(self, numbers: dict[uuid.UUID, int]) -> list[dict]:
        ordered = sorted(numbers.items(), key=lambda item: item[1])
        index = []
        for source_id, number in ordered:
            source = self.session.get(SourceItem, source_id)
            asset = self.session.scalar(select(SourceAsset).where(SourceAsset.source_item_id == source_id))
            published = self._published_at(source_id)
            index.append(
                {
                    "citation_number": number,
                    "source_id": source_id,
                    "title": None if source is None else (source.display_name or "Untitled Source"),
                    "source_type": None if source is None else source.source_type,
                    "original_url": None if source is None else source.original_url,
                    "canonical_url": None if source is None else source.canonical_url,
                    "filename": None if asset is None else asset.original_filename,
                    "published_at": published,
                }
            )
        return index

    def _published_at(self, source_id: uuid.UUID) -> datetime | None:
        return self.session.scalar(
            select(OriginalSourceCandidate.published_at)
            .where(OriginalSourceCandidate.source_item_id == source_id, OriginalSourceCandidate.published_at.is_not(None))
            .order_by(OriginalSourceCandidate.published_at.desc())
        )

    def _spec(self, provider_type: str | None):
        try:
            return resolve_workflow(self.session, self.settings, "BRIEF", provider_type)
        except RoutingError:
            return None

    def _prompt_name(self, filters: dict) -> str:
        slugs = set(filters.get("category_slugs") or [])
        if len(slugs) != 1:
            return "brief-general"
        mapping = {"knowledge": "brief-knowledge", "business": "brief-business", "project_discovery": "brief-project", "other": "brief-other"}
        return mapping.get(next(iter(slugs)), "brief-general")

    def _frozen_filters(self, filters: dict) -> dict:
        start = filters.get("start_date") or date.today().isoformat()
        end = filters.get("end_date") or start
        if isinstance(start, date):
            start = start.isoformat()
        if isinstance(end, date):
            end = end.isoformat()
        topic_ids = []
        for topic_id in filters.get("topic_ids") or []:
            topic = self._canonical_topic(uuid.UUID(str(topic_id)))
            if topic is not None:
                topic_ids.append(str(topic.id))
        return {
            "start_date": date.fromisoformat(str(start)[:10]),
            "end_date": date.fromisoformat(str(end)[:10]),
            "date_basis": filters.get("date_basis") or "COLLECTED_AT",
            "detail_level": filters.get("detail_level") or "STANDARD",
            "category_slugs": list(filters.get("category_slugs") or []),
            "topic_ids": topic_ids,
            "scope": "mine",
        }

    def _canonical_topic(self, topic_id: uuid.UUID) -> Topic | None:
        topic = self.session.get(Topic, topic_id)
        seen = set()
        while topic is not None and topic.merged_into_topic_id and topic.id not in seen:
            seen.add(topic.id)
            topic = self.session.get(Topic, topic.merged_into_topic_id)
        return topic

    def _topic_family(self, canonical_id: uuid.UUID) -> set[uuid.UUID]:
        ids = {canonical_id}
        pending = [canonical_id]
        while pending:
            current = pending.pop()
            children = list(self.session.scalars(select(Topic.id).where(Topic.merged_into_topic_id == current)))
            for child in children:
                if child not in ids:
                    ids.add(child)
                    pending.append(child)
        return ids

    def _mark_uncited(self, brief: Brief, cited_ids: set[uuid.UUID]) -> None:
        rows = list(self.session.scalars(select(BriefSource).where(BriefSource.brief_id == brief.id)))
        changed = False
        for row in rows:
            if row.included and row.source_item_id not in cited_ids:
                row.included = False
                row.exclusion_reason = "NOT_CITED"
                changed = True
        if not changed:
            return
        brief.included_source_count = len([row for row in rows if row.included])
        brief.excluded_source_count = len(rows) - brief.included_source_count
        brief.exclusion_reasons_json = {}
        for row in rows:
            if row.exclusion_reason:
                brief.exclusion_reasons_json[row.exclusion_reason] = brief.exclusion_reasons_json.get(row.exclusion_reason, 0) + 1

    def _reason_counts(self, rows: list[dict]) -> dict:
        counts = {}
        for row in rows:
            if row["exclusion_reason"]:
                counts[row["exclusion_reason"]] = counts.get(row["exclusion_reason"], 0) + 1
        return counts

    def _brief_diagnosis(self, primaries: list[dict], included: list[dict]) -> dict:
        if not primaries:
            return {"code": "BRIEF_NO_SOURCES_IN_RANGE", "message": "所选日期与分类范围内没有任何收藏资料。"}
        if not included:
            top = self._reason_counts(primaries)
            if top.get("NO_ANALYSIS"):
                return {"code": "BRIEF_NO_ANALYZED_SOURCES", "message": "范围内有资料，但尚未完成 AI 分析。"}
            if top.get("EXTRACTION_FAILED") or top.get("NO_CURRENT_DOCUMENT"):
                return {"code": "BRIEF_NO_USABLE_CONTENT", "message": "范围内有资料，但正文提取不可用。"}
            return {"code": "BRIEF_EXCLUDED_BY_FILTERS", "message": "范围内有资料，但当前筛选条件下均不可用于简报。"}
        return {"code": "BRIEF_READY", "message": f"找到 {len(primaries)} 条资料，其中 {len(included)} 条可用于生成简报。"}

    def _finish_brief(self, brief: Brief, status: str, code: str | None, message: str | None) -> Brief:
        brief.status = status
        brief.error_code = code
        if message and status in {"NO_CONTENT", "FAILED"}:
            brief.error_message = message
            brief.content_markdown = message
        brief.completed_at = datetime.now(timezone.utc)
        self.session.commit()
        return brief

    def _safe_generation_diagnostics(self, usage: dict | None) -> dict:
        if not isinstance(usage, dict):
            return {}
        return {
            "request_count": int(usage.get("request_count") or 0),
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
            "latency_ms": int(usage.get("latency_ms") or 0),
            "reduction_levels": int(usage.get("reduction_levels") or 0),
            "requested_provider": usage.get("requested_provider"),
            "actual_provider": usage.get("actual_provider"),
            "model": usage.get("model"),
            "attempts": usage.get("attempts", [])[-20:],
        }

    def _store_failure_diagnostics(self, brief: Brief, spec, diagnostics: dict | None) -> None:
        safe = self._safe_generation_diagnostics(diagnostics)
        brief.provider_type = safe.get("actual_provider") or safe.get("requested_provider") or spec.provider_type
        brief.model_name = safe.get("model") or spec.model
        brief.input_tokens = safe.get("input_tokens") or None
        brief.output_tokens = safe.get("output_tokens") or None
        brief.total_tokens = safe.get("total_tokens") or None
        brief.latency_ms = safe.get("latency_ms") or None
        brief.filters_json = {**(brief.filters_json or {}), "generation_diagnostics": safe}

    def _add_usage(self, usage: dict, response) -> None:
        usage["request_count"] = int(usage.get("request_count", 0)) + 1
        usage["input_tokens"] += response.input_tokens or 0
        usage["output_tokens"] += response.output_tokens or 0
        usage["total_tokens"] += response.total_tokens or 0
        usage["latency_ms"] += response.latency_ms or 0


def _jsonable(value):
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def render_markdown(payload: dict, sources: list[dict]) -> str:
    lines = [f"# {payload.get('title') or '学习摘要'}", "", "## What we know", payload.get("executive_summary") or "", ""]
    if payload.get("themes"):
        lines.append("## Common themes")
    for theme in payload.get("themes") or []:
        lines.extend([f"## {theme['title']}", "", theme.get("summary") or ""])
        for point in theme.get("points") or []:
            marks = "".join(f"[{citation['citation_number']}]" for citation in point["citations"])
            lines.append(f"- ({point['statement_type']}) {point['text']} {marks}".rstrip())
        lines.append("")
    for title, key in (
        ("Facts", "key_facts"),
        ("Views", "agreements"),
        ("Disagreements", "disagreements"),
        ("Timeline", "new_developments"),
        ("Open questions", "open_questions"),
        ("Synthesis", "knowledge_to_remember"),
    ):
        points = payload.get(key) or []
        if not points:
            continue
        lines.append(f"## {title}")
        for point in points:
            marks = "".join(f"[{citation['citation_number']}]" for citation in point["citations"])
            lines.append(f"- ({point['statement_type']}) {point['text']} {marks}".rstrip())
        lines.append("")
    lines.append("## Sources")
    for source in sources:
        lines.append(f"[{source['citation_number']}] {source['title']}")
        lines.append(f"Type: {source['source_type']}")
        url = source.get("canonical_url") or source.get("original_url")
        if url:
            lines.append(f"URL: {url}")
        elif source.get("filename"):
            lines.append(f"用户上传：{source['filename']}")
        else:
            lines.append("用户上传文本")
        lines.append("")
    return "\n".join(lines).strip() + "\n"
