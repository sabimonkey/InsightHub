import json
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import PROJECT_ROOT, Settings, get_settings
from app.models.extraction import ContentChunk, ExtractedDocument
from app.models.retrieval import AskCitation, AskSession, AskTurn
from app.models.source_item import SourceItem
from app.services.analysis.schema import extract_json_object
from app.services.llm.provider import FakeLLMProvider
from app.services.llm.registry import build_provider
from app.services.llm.routing import RoutingError, resolve_workflow
from app.services.llm.types import LLMError, LLMRequest
from app.services.retrieval.ask_events import AskTurnEventPublisher
from app.services.retrieval.ask_partial import partial_answer_text
from app.services.retrieval.coverage import ANSWER_SCHEMA, COVERAGE, FOCUSED, PLAN_SCHEMA, apply_coverage_contract, parse_plan
from app.services.retrieval.embedding import EmbeddingError
from app.services.retrieval.ask_title import derive_ask_session_title
from app.services.retrieval.search import SearchService


class AskService:
    def __init__(self, session: Session, settings: Settings | None = None, *, inline: bool = False, enqueue=None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.inline = inline
        self.enqueue = enqueue

    def create_session(self, title: str | None = None) -> AskSession:
        now = datetime.now(timezone.utc)
        from app.services.system_scope import creation_scope_from_settings

        row = AskSession(
            id=uuid.uuid4(),
            title=(title or None),
            created_at=now,
            updated_at=now,
            system_scope=creation_scope_from_settings(self.settings),
            title_locked=bool((title or "").strip()),
        )
        self.session.add(row)
        self.session.commit()
        return row

    def soft_delete_session(self, session_id: uuid.UUID) -> None:
        row = self.session.get(AskSession, session_id)
        if row is None or row.deleted_at is not None:
            raise LookupError("ASK_SESSION_NOT_FOUND")
        row.deleted_at = datetime.now(timezone.utc)
        self.session.commit()

    def clear_sessions(self) -> int:
        from app.services.system_scope import api_visibility_filter

        rows = list(
            self.session.scalars(
                select(AskSession).where(api_visibility_filter(AskSession.system_scope)).where(AskSession.deleted_at.is_(None))
            )
        )
        now = datetime.now(timezone.utc)
        for row in rows:
            row.deleted_at = now
        self.session.commit()
        return len(rows)

    def start_turn(self, session_id: uuid.UUID, question: str, filters: dict | None = None, provider_type: str | None = None) -> AskTurn:
        ask_session = self.session.get(AskSession, session_id)
        if ask_session is None or ask_session.deleted_at is not None:
            raise LookupError("ASK_SESSION_NOT_FOUND")
        previous = list(self.session.scalars(select(AskTurn).where(AskTurn.session_id == session_id).order_by(AskTurn.created_at.desc()).limit(self.settings.ask_history_turns)))
        retrieval_query = " ".join([question] + [row.question for row in reversed(previous)])
        turn = AskTurn(
            id=uuid.uuid4(),
            session_id=session_id,
            question=question,
            provider_type=provider_type,
            model_name=None,
            status="PENDING",
            answer_markdown=None,
            retrieval_query=retrieval_query,
            filters_json=filters or {},
            excluded_sensitive_source_count=0,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(turn)
        ask_session.updated_at = datetime.now(timezone.utc)
        if not ask_session.title_locked and not (ask_session.title or "").strip():
            ask_session.title = derive_ask_session_title(question)
        self.session.commit()
        if self.inline:
            return self.execute(turn.id)
        if self.enqueue is not None:
            self.enqueue(str(turn.id))
        return turn

    def execute(self, turn_id: uuid.UUID) -> AskTurn:
        turn = self.session.get(AskTurn, turn_id)
        if turn is None:
            raise LookupError("ASK_TURN_NOT_FOUND")
        turn.status = "RUNNING"
        self.session.commit()
        publisher = self._open_publisher(turn)
        user_filters = {key: value for key, value in dict(turn.filters_json or {}).items() if key != "retrieval"}
        try:
            planner_spec = resolve_workflow(self.session, self.settings, "ASK_PLANNER", turn.provider_type)
            answer_spec = resolve_workflow(self.session, self.settings, "ASK_ANSWER", turn.provider_type)
        except RoutingError as exc:
            return self._finish(turn, "FAILED", exc.code, exc.message, publisher=publisher)
        privacy = ["PUBLIC", "PRIVATE", "SENSITIVE"] if answer_spec.is_local else ["PUBLIC", "PRIVATE"]
        planner = self._open_provider(planner_spec)
        if publisher:
            publisher.publish("planning", {})
        plan = self._plan(planner, turn.question)
        if publisher:
            publisher.publish("retrieving", {})
        search = SearchService(self.session, self.settings)
        started = time.perf_counter()
        try:
            if plan["mode"] == COVERAGE:
                covered = search.cover(turn.retrieval_query, {**user_filters, "eligible_privacy": privacy})
                hits = [item for item in covered["hits"] if item.get("chunk_id")]
                raw_sources = search._scope_sources(user_filters)
                allowed_ids = {str(item["id"]) for item in search._scope_sources({**user_filters, "eligible_privacy": privacy})}
                excluded = {str(item["id"]) for item in raw_sources if item.get("privacy_level") == "SENSITIVE" and str(item["id"]) not in allowed_ids}
                meta = {
                    "retrieval_mode": COVERAGE,
                    "eligible_source_count": covered["eligible_source_count"],
                    "retrieved_source_count": covered["retrieved_source_count"],
                    "retrieved_source_ids": covered["retrieved_source_ids"],
                    "missing_source_ids": covered["missing_source_ids"],
                    "missing_titles": covered["missing_titles"],
                    "coverage_complete": covered["coverage_complete"],
                    "coverage_limited": covered["coverage_limited"],
                    "coverage_limit": covered["coverage_limit"],
                    "coverage_fallback_used": covered["coverage_fallback_used"],
                    "chunks_per_source": covered["chunks_per_source"],
                    "retrieval_reasons": covered["retrieval_reasons"],
                }
            else:
                raw = search.search(turn.retrieval_query, user_filters, mode="hybrid")
                excluded = {item["source_id"] for item in raw["results"] if item.get("privacy_level") == "SENSITIVE" and not answer_spec.is_local}
                allowed = search.search(turn.retrieval_query, {**user_filters, "eligible_privacy": privacy}, mode="hybrid")
                hits = [item for item in allowed["results"] if item.get("chunk_id")]
                retrieved_ids = list(dict.fromkeys(str(item["source_id"]) for item in hits if item.get("source_id")))
                meta = {
                    "retrieval_mode": FOCUSED,
                    "eligible_source_count": len(retrieved_ids),
                    "retrieved_source_count": len(retrieved_ids),
                    "retrieved_source_ids": retrieved_ids,
                    "missing_source_ids": [],
                    "missing_titles": [],
                    "coverage_complete": None,
                    "coverage_limited": False,
                    "coverage_limit": self.settings.ask_max_coverage_sources,
                    "coverage_fallback_used": False,
                    "chunks_per_source": {},
                    "retrieval_reasons": {},
                }
        except EmbeddingError:
            self.session.rollback()
            turn = self.session.get(AskTurn, turn_id)
            return self._finish(turn, "FAILED", "RETRIEVAL_DEPENDENCY_UNAVAILABLE", "知识检索服务暂时不可用，请稍后重试。", publisher=publisher)
        meta["planner_provider_type"] = planner_spec.provider_type
        meta["planner_model"] = getattr(planner, "model", planner_spec.model)
        meta["planner_is_local"] = planner_spec.is_local
        meta["answer_provider_type"] = answer_spec.provider_type
        meta["answer_is_local"] = answer_spec.is_local
        meta["retrieval_latency_ms"] = int((time.perf_counter() - started) * 1000)
        meta["planner_reason"] = plan["reason"]
        meta["planner_fallback"] = plan["fallback"]
        meta["planner_structured_parse_failed"] = bool(plan.get("structured_parse_failed"))
        meta["planner_latency_ms"] = plan["planner_latency_ms"]
        meta["needs_cross_source"] = plan["needs_cross_source"]
        turn.excluded_sensitive_source_count = len(excluded)
        if not hits:
            self._remember(turn, user_filters, meta)
            return self._finish(turn, "NO_EVIDENCE", None, "当前 InsightHub 中没有足够资料回答这个问题。", publisher=publisher)
        context = self._pack(hits, expand_neighbors=plan["mode"] != COVERAGE)
        self._align_coverage(meta, context)
        evidence = self._evidence(context)
        system = (PROJECT_ROOT / "prompts" / "ask" / "v1" / "system.md").read_text(encoding="utf-8")
        user = (PROJECT_ROOT / "prompts" / "ask" / "v1" / "user.md").read_text(encoding="utf-8")
        missing = "、".join(meta["missing_titles"]) if meta["missing_titles"] else "none"
        coverage_label = "not_applicable" if meta["coverage_complete"] is None else str(bool(meta["coverage_complete"])).lower()
        user = (
            user.replace("{{question}}", turn.question)
            .replace("{{mode}}", meta["retrieval_mode"])
            .replace("{{eligible_count}}", str(meta["eligible_source_count"]))
            .replace("{{retrieved_count}}", str(meta["retrieved_source_count"]))
            .replace("{{coverage_complete}}", coverage_label)
            .replace("{{missing_sources}}", missing)
            .replace("{{evidence}}", evidence)
        )
        if "<source_content>" in system or "ignore previous" in system.lower() and "untrusted" not in system.lower():
            self._remember(turn, user_filters, meta)
            return self._finish(turn, "FAILED", "PROMPT_ISOLATION", "系统提示被资料污染。", publisher=publisher)
        provider = self._open_provider(answer_spec)
        answer_request = LLMRequest(
            system_prompt=system,
            user_content=user,
            response_schema=ANSWER_SCHEMA if getattr(provider, "supports_json_schema", False) else None,
            temperature=0,
            max_output_tokens=self.settings.analysis_max_output_tokens,
            metadata={"purpose": "ask_answer", "schema_name": "ask_answer"},
        )
        if publisher:
            publisher.publish("answer_started", {})
        stream_buffer = ""
        last_visible_len = 0

        def _on_stream_delta(raw: str) -> None:
            nonlocal stream_buffer, last_visible_len
            stream_buffer += raw
            visible = partial_answer_text(stream_buffer)
            if publisher and len(visible) > last_visible_len:
                publisher.delta(visible[last_visible_len:])
                last_visible_len = len(visible)

        try:
            if self._use_answer_streaming(answer_spec, provider) and hasattr(provider, "stream_completion"):
                response = provider.stream_completion(answer_request, on_delta=_on_stream_delta)
                meta["answer_streaming"] = True
            else:
                response = provider.complete(answer_request)
                meta["answer_streaming"] = False
        except LLMError as exc:
            self._remember(turn, user_filters, meta)
            return self._finish(turn, "FAILED", exc.code, exc.message, publisher=publisher)
        turn.provider_type = answer_spec.provider_type
        turn.model_name = response.model
        meta["answer_output_strategy"] = (response.raw_response_metadata or {}).get("strategy")
        meta["time_to_first_token_ms"] = (response.raw_response_metadata or {}).get("time_to_first_token_ms")
        meta["answer_stream_duration_ms"] = (response.raw_response_metadata or {}).get("answer_stream_duration_ms")
        meta["finish_reason"] = response.finish_reason
        turn.input_tokens = _add_tokens(plan.get("input_tokens"), response.input_tokens)
        turn.output_tokens = _add_tokens(plan.get("output_tokens"), response.output_tokens)
        turn.latency_ms = response.latency_ms
        meta["generation_latency_ms"] = response.latency_ms
        if publisher:
            publisher.publish("validating", {})
        payload = self._parse_answer_payload(provider, answer_request, response.text, stream_buffer)
        if payload is None:
            self._remember(turn, user_filters, meta)
            return self._finish(turn, "FAILED", "STRUCTURED_OUTPUT_INVALID", "回答不是有效 JSON。", publisher=publisher)
        answer_value = payload.get("answer")
        if not isinstance(answer_value, str) or not isinstance(payload.get("citations") or [], list):
            self._remember(turn, user_filters, meta)
            return self._finish(turn, "FAILED", "STRUCTURED_OUTPUT_INVALID", "回答不是有效 JSON。", publisher=publisher)
        answer = answer_value
        allowed_chunks = {str(item["chunk"].id): item for item in context}
        number = 1
        valid = 0
        for citation in payload.get("citations") or []:
            chunk_id = str(citation.get("chunk_id") or "")
            quote = str(citation.get("quote") or "")
            item = allowed_chunks.get(chunk_id)
            if item is None:
                continue
            normalized = " ".join(item["chunk"].content.split())
            if quote and " ".join(quote.split()) not in normalized:
                continue
            document = self.session.get(ExtractedDocument, item["chunk"].extracted_document_id)
            self.session.add(
                AskCitation(
                    id=uuid.uuid4(),
                    ask_turn_id=turn.id,
                    content_chunk_id=item["chunk"].id,
                    source_item_id=document.source_item_id,
                    citation_number=number,
                    quote_text=quote[:500],
                    retrieval_score=item["score"],
                    created_at=datetime.now(timezone.utc),
                )
            )
            number += 1
            valid += 1
        answer, scope_code = apply_coverage_contract(
            answer,
            mode=meta["retrieval_mode"],
            eligible=int(meta["eligible_source_count"] or 0),
            retrieved=int(meta["retrieved_source_count"] or 0),
            limit=int(meta["coverage_limit"] or 0),
            limited=bool(meta["coverage_limited"]),
            missing_titles=list(meta["missing_titles"]),
        )
        self._remember(turn, user_filters, meta)
        if valid == 0:
            return self._finish(turn, "PARTIAL", "NO_VALIDATED_CITATIONS", answer or "No validated citations.", publisher=publisher)
        if "[1]" not in answer:
            answer = f"{answer} " + " ".join(f"[{index}]" for index in range(1, valid + 1))
        if scope_code:
            return self._finish(turn, "PARTIAL", scope_code, answer, publisher=publisher)
        return self._finish(turn, "SUCCEEDED", None, answer, publisher=publisher)

    def _open_publisher(self, turn: AskTurn) -> AskTurnEventPublisher | None:
        if not self.settings.ask_streaming_enabled:
            return None
        try:
            publisher = AskTurnEventPublisher(turn.id, self.settings)
            publisher.publish("turn_started", {"turn_id": str(turn.id), "session_id": str(turn.session_id)})
            return publisher
        except Exception:
            return None

    def _use_answer_streaming(self, answer_spec, provider) -> bool:
        if not self.settings.ask_streaming_enabled:
            return False
        if answer_spec.provider_type == "FAKE":
            return bool(getattr(provider, "supports_streaming", True))
        if not getattr(provider, "supports_streaming", False):
            return False
        return bool((answer_spec.capabilities or {}).get("supports_streaming"))

    def _open_provider(self, spec):
        if spec.provider_type == "FAKE":
            return FakeLLMProvider()
        return build_provider(spec, self.settings, session=self.session)

    def _parse_answer_payload(self, provider, base_request: LLMRequest, text: str, stream_buffer: str) -> dict | None:
        candidates = [text, stream_buffer]
        for raw in candidates:
            if not raw or not raw.strip():
                continue
            try:
                return extract_json_object(raw)
            except (ValueError, json.JSONDecodeError):
                continue
        repair = LLMRequest(
            system_prompt=base_request.system_prompt,
            user_content=(text or stream_buffer or "") + "\n\nReturn valid JSON only with keys answer (string) and citations (array).",
            response_schema=ANSWER_SCHEMA if getattr(provider, "supports_json_schema", False) else None,
            temperature=0,
            max_output_tokens=min(2048, base_request.max_output_tokens or 2048),
            metadata={"purpose": "ask_answer_repair", "schema_name": "ask_answer"},
        )
        try:
            repaired = provider.complete(repair)
            return extract_json_object(repaired.text)
        except (LLMError, ValueError, json.JSONDecodeError):
            return None

    def _plan(self, provider, question: str) -> dict:
        system = (PROJECT_ROOT / "prompts" / "ask" / "v1" / "planner_system.md").read_text(encoding="utf-8")
        user = (PROJECT_ROOT / "prompts" / "ask" / "v1" / "planner_user.md").read_text(encoding="utf-8").replace("{{question}}", question)
        started = time.perf_counter()
        fallback = {
            "mode": FOCUSED,
            "needs_cross_source": False,
            "requested_scope": "CURRENT_FILTER_SCOPE",
            "reason": "planner_fallback",
            "fallback": True,
            "structured_parse_failed": False,
            "planner_latency_ms": 0,
            "input_tokens": None,
            "output_tokens": None,
        }
        response = None
        parsed = None
        token_budgets = (256, 1024)
        try:
            for max_out in token_budgets:
                response = provider.complete(
                    LLMRequest(
                        system_prompt=system,
                        user_content=user,
                        response_schema=PLAN_SCHEMA,
                        temperature=0,
                        max_output_tokens=max_out,
                        metadata={"purpose": "ask_plan", "schema_name": "ask_plan"},
                    )
                )
                parsed = parse_plan(response.text)
                if parsed is not None:
                    break
                if max_out >= token_budgets[-1]:
                    break
        except Exception:
            fallback["planner_latency_ms"] = int((time.perf_counter() - started) * 1000)
            fallback["structured_parse_failed"] = True
            return fallback
        latency = int((time.perf_counter() - started) * 1000)
        if parsed is None:
            fallback["planner_latency_ms"] = latency
            fallback["input_tokens"] = response.input_tokens
            fallback["output_tokens"] = response.output_tokens
            fallback["reason"] = "structured_parse_failed"
            fallback["structured_parse_failed"] = True
            return fallback
        parsed["fallback"] = False
        parsed["structured_parse_failed"] = False
        parsed["planner_latency_ms"] = latency
        parsed["input_tokens"] = response.input_tokens
        parsed["output_tokens"] = response.output_tokens
        return parsed

    def _align_coverage(self, meta: dict, context: list[dict]) -> None:
        if meta["retrieval_mode"] != COVERAGE:
            counts: dict[str, int] = {}
            for item in context:
                if item["role"] != "hit":
                    continue
                source_id = str(item["source_id"])
                counts[source_id] = counts.get(source_id, 0) + 1
            meta["chunks_per_source"] = counts
            return
        packed_ids = list(dict.fromkeys(str(item["source_id"]) for item in context))
        dropped = [source_id for source_id in meta["retrieved_source_ids"] if source_id not in packed_ids]
        meta["retrieved_source_ids"] = packed_ids
        meta["retrieved_source_count"] = len(packed_ids)
        meta["missing_source_ids"] = list(dict.fromkeys([*meta["missing_source_ids"], *dropped]))
        counts: dict[str, int] = {}
        reasons: dict[str, str] = {}
        for item in context:
            source_id = str(item["source_id"])
            if item["role"] == "hit":
                counts[source_id] = counts.get(source_id, 0) + 1
            reason = str(item.get("retrieval_reason") or "RELEVANCE")
            if reason == "COVERAGE_FALLBACK" or source_id not in reasons:
                reasons[source_id] = reason
        meta["chunks_per_source"] = counts
        meta["retrieval_reasons"] = reasons
        meta["coverage_fallback_used"] = any(reason == "COVERAGE_FALLBACK" for reason in reasons.values())
        meta["coverage_complete"] = (
            not meta["coverage_limited"]
            and not meta["missing_source_ids"]
            and meta["retrieved_source_count"] == meta["eligible_source_count"]
        )

    def _evidence(self, context: list[dict]) -> str:
        order: list[str] = []
        grouped: dict[str, dict] = {}
        for item in context:
            source_id = str(item["source_id"])
            if source_id not in grouped:
                order.append(source_id)
                grouped[source_id] = {"source": item["source"], "items": []}
            grouped[source_id]["items"].append(item)
        blocks = []
        for source_id in order:
            source = grouped[source_id]["source"]
            url = source.canonical_url or source.original_url or ""
            lines = [f"SOURCE {source.id}", f"title: {source.display_name or 'Untitled Source'}", f"url: {url}"]
            for item in grouped[source_id]["items"]:
                reason = item.get("retrieval_reason") or "RELEVANCE"
                lines.append(f"[CHUNK: {item['chunk'].id}] role={item['role']} retrieval={reason}")
                lines.append(item["chunk"].content)
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    def _pack(self, hits: list[dict], *, expand_neighbors: bool = True) -> list[dict]:
        budget = max(500, (self.settings.default_llm_context_window - self.settings.analysis_max_output_tokens) * 3)
        ordered = hits
        if not expand_neighbors:
            first = []
            rest = []
            seen_sources = set()
            for hit in hits:
                source_id = str(hit.get("source_id") or "")
                if source_id not in seen_sources:
                    first.append(hit)
                    seen_sources.add(source_id)
                else:
                    rest.append(hit)
            ordered = first + rest
        used = 0
        packed = []
        seen = set()
        included_sources = set()
        for hit in ordered:
            chunk = self.session.get(ContentChunk, hit["chunk_id"])
            if chunk is None or chunk.id in seen:
                continue
            document = self.session.get(ExtractedDocument, chunk.extracted_document_id)
            source = None if document is None else self.session.get(SourceItem, document.source_item_id)
            if source is None:
                continue
            if used + len(chunk.content) > budget and (expand_neighbors or str(source.id) in included_sources or packed):
                if expand_neighbors:
                    break
                continue
            packed.append(
                {
                    "chunk": chunk,
                    "role": "hit",
                    "score": hit["score"],
                    "source": source,
                    "source_id": source.id,
                    "retrieval_reason": hit.get("retrieval_reason") or "RELEVANCE",
                }
            )
            seen.add(chunk.id)
            included_sources.add(str(source.id))
            used += len(chunk.content)
            if not expand_neighbors:
                continue
            for neighbor in self.session.scalars(
                select(ContentChunk).where(
                    ContentChunk.extracted_document_id == chunk.extracted_document_id,
                    ContentChunk.sequence.in_([chunk.sequence - 1, chunk.sequence + 1]),
                )
            ):
                if neighbor.id in seen or used + len(neighbor.content) > budget:
                    continue
                packed.append(
                    {
                        "chunk": neighbor,
                        "role": "context_expansion",
                        "score": hit["score"],
                        "source": source,
                        "source_id": source.id,
                        "retrieval_reason": hit.get("retrieval_reason") or "RELEVANCE",
                    }
                )
                seen.add(neighbor.id)
                used += len(neighbor.content)
        return packed

    def _remember(self, turn: AskTurn, user_filters: dict, meta: dict) -> None:
        turn.filters_json = {**user_filters, "retrieval": meta}
        flag_modified(turn, "filters_json")

    def _finish(
        self,
        turn: AskTurn,
        status: str,
        code: str | None,
        message: str | None,
        *,
        publisher: AskTurnEventPublisher | None = None,
    ) -> AskTurn:
        turn.status = status
        turn.error_code = code
        turn.answer_markdown = message
        turn.error_message = None if status in {"SUCCEEDED", "PARTIAL", "NO_EVIDENCE"} else message
        turn.completed_at = datetime.now(timezone.utc)
        self.session.commit()
        if publisher is not None:
            from app.services.retrieval.ask_turn_view import build_ask_final_sse_payload

            fresh = self.session.get(AskTurn, turn.id) or turn
            if status in {"SUCCEEDED", "PARTIAL", "NO_EVIDENCE"}:
                publisher.publish("final", build_ask_final_sse_payload(self.session, fresh))
            else:
                publisher.publish("error", {"code": code or status, "message": message or ""})
            publisher.close()
        return turn


def _add_tokens(left: int | None, right: int | None) -> int | None:
    if left is None and right is None:
        return None
    return (left or 0) + (right or 0)
