import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.discovery import OriginalSourceCandidate, SourceDiscoveryRun, SourceRelation
from app.models.enums import CandidateStatus, ConfirmedBy, DiscoveryStatus, RelationType, SourceType
from app.models.extraction import ExtractedDocument
from app.models.ingestion_record import IngestionRecord
from app.models.source_item import SourceItem
from app.services.discovery.ranking import CandidateDraft, merge_drafts
from app.services.discovery.resolvers import RESOLVER_VERSION, ImageSourceResolver, TextSourceResolver, UrlSourceResolver
from app.services.discovery.search import DisabledSearchProvider, SearchProvider
from app.services.extraction.ssrf import SsrfError, assert_public_http_url
from app.services.ingestion.errors import IngestionError
from app.services.ingestion.service import IngestionService
from app.services.ingestion.url_normalization import canonicalize_url


class DiscoveryError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class DiscoveryService:
    def __init__(
        self,
        session: Session,
        ingestion: IngestionService,
        *,
        inline: bool,
        search: SearchProvider | None = None,
        enqueue=None,
        extraction=None,
        timeout: float = 20,
        max_bytes: int = 5_000_000,
        max_redirects: int = 5,
        http_client=None,
        resolver=None,
    ) -> None:
        self.session = session
        self.ingestion = ingestion
        self.inline = inline
        self.search = search or DisabledSearchProvider()
        self.enqueue = enqueue
        self.extraction = extraction
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.http_client = http_client
        self.resolver = resolver

    def start(self, source_id: uuid.UUID) -> SourceDiscoveryRun:
        source = self._source(source_id)
        run = SourceDiscoveryRun(
            id=uuid.uuid4(),
            source_item_id=source.id,
            status=DiscoveryStatus.PENDING.value,
            resolver_type=self._resolver_type(source),
            resolver_version=RESOLVER_VERSION,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(run)
        self.session.commit()
        if self.inline:
            return self.execute(run.id)
        if self.enqueue is None:
            return self._fail(run, "QUEUE_UNAVAILABLE", "发现任务没有进入队列。")
        try:
            self.enqueue(str(run.id))
        except Exception as exc:
            return self._fail(run, "QUEUE_UNAVAILABLE", str(exc)[:300])
        self.session.refresh(run)
        return run

    def execute(self, run_id: uuid.UUID) -> SourceDiscoveryRun:
        run = self.session.get(SourceDiscoveryRun, run_id)
        if run is None:
            raise DiscoveryError(404, "DISCOVERY_NOT_FOUND", "找不到发现任务。")
        run.status = DiscoveryStatus.RUNNING.value
        run.started_at = datetime.now(timezone.utc)
        self.session.commit()
        source = self._source(run.source_item_id)
        try:
            drafts, summary, error_code, error_message = self._resolve(source)
            self._store_candidates(run, source, drafts)
            if error_code and drafts:
                run.status = DiscoveryStatus.PARTIAL.value
            elif error_code:
                run.status = DiscoveryStatus.FAILED.value
            else:
                run.status = DiscoveryStatus.SUCCEEDED.value
            run.query_summary = summary
            run.error_code = error_code
            run.error_message = error_message
            run.completed_at = datetime.now(timezone.utc)
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            run = self.session.get(SourceDiscoveryRun, run_id)
            if run is not None:
                self._fail(run, "DISCOVERY_FAILED", type(exc).__name__)
        if run is None:
            raise DiscoveryError(404, "DISCOVERY_NOT_FOUND", "找不到发现任务。")
        self.session.refresh(run)
        return run

    def current(self, source_id: uuid.UUID) -> tuple[SourceDiscoveryRun | None, list[OriginalSourceCandidate], list[SourceRelation]]:
        self._source(source_id)
        run = self.session.scalar(
            select(SourceDiscoveryRun)
            .where(SourceDiscoveryRun.source_item_id == source_id)
            .order_by(SourceDiscoveryRun.created_at.desc(), SourceDiscoveryRun.id.desc())
        )
        candidates: list[OriginalSourceCandidate] = []
        if run is not None:
            candidates = list(
                self.session.scalars(
                    select(OriginalSourceCandidate)
                    .where(OriginalSourceCandidate.discovery_run_id == run.id)
                    .order_by(OriginalSourceCandidate.rank.asc())
                ).all()
            )
        relations = list(
            self.session.scalars(
                select(SourceRelation).where(SourceRelation.from_source_id == source_id).order_by(SourceRelation.created_at.asc())
            ).all()
        )
        return run, candidates, relations

    def add_manual(self, source_id: uuid.UUID, raw_url: str) -> OriginalSourceCandidate:
        source = self._source(source_id)
        try:
            original, canonical = canonicalize_url(raw_url)
            assert_public_http_url(canonical, self.resolver)
        except IngestionError as exc:
            raise DiscoveryError(exc.status_code, exc.code, exc.message) from exc
        except SsrfError as exc:
            raise DiscoveryError(400, exc.code, exc.message) from exc
        run = self.session.scalar(
            select(SourceDiscoveryRun)
            .where(SourceDiscoveryRun.source_item_id == source.id)
            .order_by(SourceDiscoveryRun.created_at.desc())
        )
        if run is None or run.status in {DiscoveryStatus.PENDING.value, DiscoveryStatus.RUNNING.value}:
            run = SourceDiscoveryRun(
                id=uuid.uuid4(),
                source_item_id=source.id,
                status=DiscoveryStatus.SUCCEEDED.value,
                resolver_type="MANUAL",
                resolver_version=RESOLVER_VERSION,
                query_summary="manual",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
            )
            self.session.add(run)
            self.session.flush()
        rejected = self._previously_rejected(source.id, canonical)
        candidate = OriginalSourceCandidate(
            id=uuid.uuid4(),
            discovery_run_id=run.id,
            source_item_id=source.id,
            candidate_url=original,
            normalized_candidate_url=canonical,
            title=None,
            candidate_type="MANUAL",
            score=0.5,
            confidence=0.5,
            match_reasons_json=["manual candidate"],
            evidence_json={"provenance": "MANUAL", "previously_rejected": rejected, "untrusted_content": True},
            rank=self._next_rank(run.id),
            status=CandidateStatus.PROPOSED.value,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(candidate)
        self.session.commit()
        return candidate

    def confirm(self, candidate_id: uuid.UUID) -> tuple[OriginalSourceCandidate, SourceRelation, SourceItem]:
        candidate = self.session.get(OriginalSourceCandidate, candidate_id)
        if candidate is None:
            raise DiscoveryError(404, "CANDIDATE_NOT_FOUND", "找不到候选来源。")
        if candidate.status == CandidateStatus.REJECTED.value:
            raise DiscoveryError(409, "CANDIDATE_REJECTED", "该候选已被拒绝。")
        source = self._source(candidate.source_item_id)
        try:
            _original, canonical = canonicalize_url(candidate.candidate_url)
            assert_public_http_url(canonical, self.resolver)
        except IngestionError as exc:
            raise DiscoveryError(exc.status_code, exc.code, exc.message) from exc
        except SsrfError as exc:
            raise DiscoveryError(400, exc.code, exc.message) from exc
        existing_relation = self.session.scalar(
            select(SourceRelation).where(
                SourceRelation.from_source_id == source.id,
                SourceRelation.relation_type == RelationType.RESOLVES_TO.value,
                SourceRelation.candidate_id == candidate.id,
            )
        )
        if existing_relation is not None and candidate.status == CandidateStatus.CONFIRMED.value:
            target = self.session.get(SourceItem, existing_relation.to_source_id)
            return candidate, existing_relation, target
        created = self.ingestion.ingest_discovered_url(canonical)
        target = created.source_item
        relation = self.session.scalar(
            select(SourceRelation).where(
                SourceRelation.from_source_id == source.id,
                SourceRelation.to_source_id == target.id,
                SourceRelation.relation_type == RelationType.RESOLVES_TO.value,
            )
        )
        if relation is None:
            relation = SourceRelation(
                id=uuid.uuid4(),
                from_source_id=source.id,
                to_source_id=target.id,
                relation_type=RelationType.RESOLVES_TO.value,
                confirmed_by=ConfirmedBy.USER.value,
                candidate_id=candidate.id,
                created_at=datetime.now(timezone.utc),
            )
            self.session.add(relation)
        candidate.status = CandidateStatus.CONFIRMED.value
        before_type = source.source_type
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            relation = self.session.scalar(
                select(SourceRelation).where(
                    SourceRelation.from_source_id == source.id,
                    SourceRelation.to_source_id == target.id,
                    SourceRelation.relation_type == RelationType.RESOLVES_TO.value,
                )
            )
            candidate = self.session.get(OriginalSourceCandidate, candidate_id)
            candidate.status = CandidateStatus.CONFIRMED.value
            self.session.commit()
        source = self.session.get(SourceItem, source.id)
        if source.source_type != before_type:
            raise DiscoveryError(500, "SOURCE_IDENTITY_CHANGED", "确认来源时不应改变原资料类型。")
        if self.extraction is not None and created.ingestion_record.origin == "SYSTEM_DISCOVERY" and not created.duplicate_detected:
            try:
                self.extraction.schedule(target.id, "AUTO", force=False)
            except Exception:
                pass
        self.session.refresh(candidate)
        self.session.refresh(relation)
        target = self.session.get(SourceItem, relation.to_source_id)
        return candidate, relation, target

    def reject(self, candidate_id: uuid.UUID) -> OriginalSourceCandidate:
        candidate = self.session.get(OriginalSourceCandidate, candidate_id)
        if candidate is None:
            raise DiscoveryError(404, "CANDIDATE_NOT_FOUND", "找不到候选来源。")
        candidate.status = CandidateStatus.REJECTED.value
        evidence = dict(candidate.evidence_json or {})
        evidence["previously_rejected"] = True
        candidate.evidence_json = evidence
        self.session.commit()
        self.session.refresh(candidate)
        return candidate

    def _resolve(self, source: SourceItem):
        if source.source_type == SourceType.URL.value:
            resolver = UrlSourceResolver(self.search, self.timeout, self.max_bytes, self.max_redirects, self.http_client, self.resolver)
            return resolver.resolve(source.canonical_url or source.original_url or "")
        text = self._source_text(source)
        if source.source_type == SourceType.IMAGE.value:
            return ImageSourceResolver(self.search).resolve(text)
        return TextSourceResolver(self.search).resolve(text)

    def _source_text(self, source: SourceItem) -> str:
        document = self.session.scalar(
            select(ExtractedDocument)
            .where(ExtractedDocument.source_item_id == source.id)
            .order_by(ExtractedDocument.created_at.desc())
        )
        if document and document.plain_text:
            return document.plain_text
        record = self.session.scalar(
            select(IngestionRecord)
            .where(IngestionRecord.source_item_id == source.id)
            .order_by(IngestionRecord.collected_at.asc())
        )
        return record.original_input if record else ""

    def _store_candidates(self, run: SourceDiscoveryRun, source: SourceItem, drafts: list[CandidateDraft]) -> None:
        safe: list[CandidateDraft] = []
        for draft in merge_drafts(drafts):
            try:
                assert_public_http_url(draft.normalized_url, self.resolver)
            except SsrfError:
                continue
            rejected = self._previously_rejected(source.id, draft.normalized_url)
            if rejected:
                draft.evidence = dict(draft.evidence)
                draft.evidence["previously_rejected"] = True
                if "Previously Rejected" not in draft.match_reasons:
                    draft.match_reasons.append("Previously Rejected")
            same = source.canonical_url and draft.normalized_url == source.canonical_url
            if same:
                draft.evidence = dict(draft.evidence)
                draft.evidence["likely_original"] = True
                if "Likely Original Source" not in draft.match_reasons:
                    draft.match_reasons.append("Likely Original Source")
            safe.append(draft)
        for rank, draft in enumerate(safe, start=1):
            self.session.add(
                OriginalSourceCandidate(
                    id=uuid.uuid4(),
                    discovery_run_id=run.id,
                    source_item_id=source.id,
                    candidate_url=draft.url,
                    normalized_candidate_url=draft.normalized_url,
                    title=draft.title,
                    author=draft.author,
                    publisher=draft.publisher,
                    candidate_type=draft.candidate_type,
                    score=draft.score,
                    confidence=draft.confidence,
                    match_reasons_json=draft.match_reasons,
                    evidence_json=draft.evidence,
                    rank=rank,
                    status=CandidateStatus.PROPOSED.value,
                    created_at=datetime.now(timezone.utc),
                )
            )

    def _previously_rejected(self, source_id: uuid.UUID, canonical: str) -> bool:
        row = self.session.scalar(
            select(OriginalSourceCandidate.id).where(
                OriginalSourceCandidate.source_item_id == source_id,
                OriginalSourceCandidate.normalized_candidate_url == canonical,
                OriginalSourceCandidate.status == CandidateStatus.REJECTED.value,
            )
        )
        return row is not None

    def _next_rank(self, run_id: uuid.UUID) -> int:
        current = self.session.scalar(
            select(OriginalSourceCandidate.rank)
            .where(OriginalSourceCandidate.discovery_run_id == run_id)
            .order_by(OriginalSourceCandidate.rank.desc())
        )
        return int(current or 0) + 1

    def _resolver_type(self, source: SourceItem) -> str:
        if source.source_type == SourceType.URL.value:
            return "URL"
        if source.source_type == SourceType.IMAGE.value:
            return "IMAGE"
        return "TEXT"

    def _source(self, source_id: uuid.UUID) -> SourceItem:
        source = self.session.get(SourceItem, source_id)
        if source is None:
            raise DiscoveryError(404, "SOURCE_NOT_FOUND", "找不到该资料。")
        return source

    def _fail(self, run: SourceDiscoveryRun, code: str, message: str) -> SourceDiscoveryRun:
        run.status = DiscoveryStatus.FAILED.value
        run.error_code = code
        run.error_message = message
        run.completed_at = datetime.now(timezone.utc)
        self.session.commit()
        self.session.refresh(run)
        return run
