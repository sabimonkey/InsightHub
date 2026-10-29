"""Delete only the sources an e2e test created.

Playwright talks to the shared development database. Cleanup must wait until
this test's jobs finish, delete children before parents, and refuse the real
user sources.
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT, get_settings
from app.db.session import get_sessionmaker
from app.models.analysis import AnalysisResult, AnalysisRun, Claim, Evidence
from app.models.discovery import OriginalSourceCandidate, SourceDiscoveryRun, SourceRelation
from app.models.extraction import ContentChunk, ExtractedDocument, ExtractionRun
from app.models.ingestion_record import IngestionRecord
from app.models.organization import (
    CommercialInsight,
    CommercialInsightClaim,
    CommercialInsightEntity,
    EntityMention,
    KnowledgeCard,
    KnowledgeCardClaim,
    OrganizationRun,
    Project,
    ProjectCandidate,
    ProjectCandidateClaim,
    ProjectSource,
    SourceCategoryAssignment,
    SourceTag,
    SourceTopicAssignment,
    Topic,
    TopicAlias,
)
from app.models.retrieval import AskCitation, AskTurn, ChunkEmbedding, IndexingRun
from app.models.source_asset import SourceAsset
from app.models.source_item import SourceItem
from app.models.synthesis import (
    Brief,
    BriefCitation,
    BriefSource,
    TopicSynthesis,
    TopicSynthesisCitation,
    TopicSynthesisSource,
)

PROTECTED_CANONICAL_URLS = frozenset(
    {
        "https://x.com/ai_suxiaole/status/2106663866235261360",
        "https://x.com/denziideng/status/2106939914566922451",
        "https://x.com/bkdgiffug/status/2106962081182363902",
    }
)
_ACTIVE = ("PENDING", "RUNNING")
_DATA_ROOT = (PROJECT_ROOT / "data").resolve()


class ProtectedSourceError(RuntimeError):
    pass


class JobsNotTerminalError(RuntimeError):
    pass


def purge_markers(session: Session, markers: list[str], *, commit: bool = True, timeout_seconds: float = 45) -> None:
    names = [marker for marker in markers if marker]
    if not names:
        if commit:
            session.commit()
        return
    # Refuse protected URLs even when they are supplied directly as cleanup
    # markers rather than matching a SourceItem.display_name.
    if any(_canonical(marker) in PROTECTED_CANONICAL_URLS for marker in names):
        raise ProtectedSourceError("refusing to purge a protected source URL")
    origins = list(session.scalars(select(SourceItem).where(SourceItem.display_name.in_(names))).all())
    for source in origins:
        _refuse_protected(source)
    owned: list[SourceItem] = []
    seen: set[uuid.UUID] = set()
    for source in origins:
        for target in _discovered_targets(session, source.id):
            if target.id in seen:
                continue
            _refuse_protected(target)
            seen.add(target.id)
            owned.append(target)
    for source in origins:
        if source.id not in seen:
            seen.add(source.id)
            owned.append(source)
    if owned:
        _wait_until_terminal(session, [source.id for source in owned], timeout_seconds)
        for source in owned:
            _purge_source(session, source.id, names)
    if commit:
        session.commit()


def purge_topic(session: Session, name: str, *, commit: bool = True) -> None:
    topic_id = session.scalar(select(Topic.id).where(Topic.name == name))
    if topic_id is None:
        if commit:
            session.commit()
        return
    synthesis_ids = list(session.scalars(select(TopicSynthesis.id).where(TopicSynthesis.topic_id == topic_id)).all())
    if synthesis_ids:
        session.execute(delete(TopicSynthesisCitation).where(TopicSynthesisCitation.synthesis_id.in_(synthesis_ids)))
        session.execute(delete(TopicSynthesisSource).where(TopicSynthesisSource.synthesis_id.in_(synthesis_ids)))
        session.execute(delete(TopicSynthesis).where(TopicSynthesis.id.in_(synthesis_ids)))
    session.execute(delete(TopicAlias).where(TopicAlias.topic_id == topic_id))
    session.execute(delete(SourceTopicAssignment).where(SourceTopicAssignment.topic_id == topic_id))
    session.execute(delete(Topic).where(Topic.id == topic_id))
    if commit:
        session.commit()


def _refuse_protected(source: SourceItem) -> None:
    for value in (source.canonical_url, source.original_url):
        if _canonical(value) in PROTECTED_CANONICAL_URLS:
            raise ProtectedSourceError(f"refusing to delete protected source {source.id}")


def _canonical(value: str | None) -> str:
    if not value:
        return ""
    return value.split("?", 1)[0].rstrip("/")


def _discovered_targets(session: Session, origin_id: uuid.UUID) -> list[SourceItem]:
    relations = list(session.scalars(select(SourceRelation).where(SourceRelation.from_source_id == origin_id)).all())
    targets: list[SourceItem] = []
    for relation in relations:
        target = session.get(SourceItem, relation.to_source_id)
        if target is None or _is_protected(target):
            continue
        user_owned = session.scalar(
            select(IngestionRecord.id).where(
                IngestionRecord.source_item_id == target.id,
                IngestionRecord.origin == "USER_COLLECTION",
            )
        )
        if user_owned is not None:
            continue
        targets.append(target)
    return targets


def _is_protected(source: SourceItem) -> bool:
    return any(_canonical(value) in PROTECTED_CANONICAL_URLS for value in (source.canonical_url, source.original_url))


def _wait_until_terminal(session: Session, source_ids: list[uuid.UUID], timeout_seconds: float) -> None:
    if not source_ids:
        return
    if timeout_seconds <= 0:
        if _still_active(session, source_ids):
            raise JobsNotTerminalError("owned jobs are still pending or running")
        return
    deadline = time.monotonic() + timeout_seconds
    quiet = 0
    while True:
        session.expire_all()
        if _still_active(session, source_ids):
            quiet = 0
        else:
            quiet += 1
            if quiet >= 2:
                return
        if time.monotonic() >= deadline:
            raise JobsNotTerminalError("owned jobs did not reach a terminal state")
        time.sleep(0.2)


def _still_active(session: Session, source_ids: list[uuid.UUID]) -> bool:
    run_ids = list(session.scalars(select(ExtractionRun.id).where(ExtractionRun.source_item_id.in_(source_ids))).all())
    checks = (
        select(func.count()).select_from(ExtractionRun).where(ExtractionRun.source_item_id.in_(source_ids), ExtractionRun.status.in_(_ACTIVE)),
        select(func.count()).select_from(IndexingRun).where(IndexingRun.source_item_id.in_(source_ids), IndexingRun.status.in_(_ACTIVE)),
        select(func.count()).select_from(SourceDiscoveryRun).where(SourceDiscoveryRun.source_item_id.in_(source_ids), SourceDiscoveryRun.status.in_(_ACTIVE)),
        select(func.count()).select_from(AnalysisRun).where(AnalysisRun.source_item_id.in_(source_ids), AnalysisRun.status.in_(_ACTIVE)),
    )
    if any(int(session.scalar(query) or 0) for query in checks):
        return True
    return _queue_mentions(source_ids, run_ids)


def _queue_mentions(source_ids: list[uuid.UUID], run_ids: list[uuid.UUID]) -> bool:
    needles = {str(item) for item in [*source_ids, *run_ids]}
    if not needles:
        return False
    try:
        from redis import Redis
        from rq import Queue
        from rq.job import Job

        settings = get_settings()
        connection = Redis.from_url(settings.redis_url, socket_connect_timeout=0.5)
        queue = Queue("insighthub", connection=connection)
        job_ids = [job.id for job in queue.jobs]
        for registry in (queue.started_job_registry, queue.deferred_job_registry, queue.scheduled_job_registry):
            job_ids.extend(registry.get_job_ids())
        for job_id in job_ids:
            job = Job.fetch(job_id, connection=connection)
            blob = " ".join(str(arg) for arg in (job.args or ()))
            if any(needle in blob for needle in needles):
                return True
    except Exception:
        return False
    return False


def _purge_source(session: Session, source_id: uuid.UUID, markers: list[str]) -> None:
    source = session.get(SourceItem, source_id)
    if source is None:
        return
    _refuse_protected(source)
    documents = list(
        session.scalars(
            select(ExtractedDocument).where(
                or_(
                    ExtractedDocument.source_item_id == source_id,
                    ExtractedDocument.extraction_run_id.in_(select(ExtractionRun.id).where(ExtractionRun.source_item_id == source_id)),
                )
            )
        ).all()
    )
    document_ids = [row.id for row in documents]
    chunk_ids = []
    if document_ids:
        chunk_ids = list(session.scalars(select(ContentChunk.id).where(ContentChunk.extracted_document_id.in_(document_ids))).all())

    turn_ids: list[uuid.UUID] = []
    for marker in markers:
        turn_ids.extend(session.scalars(select(AskTurn.id).where(AskTurn.question.contains(marker))).all())
    if turn_ids:
        session.execute(delete(AskCitation).where(AskCitation.ask_turn_id.in_(turn_ids)))
        session.execute(delete(AskTurn).where(AskTurn.id.in_(turn_ids)))

    brief_ids = list(session.scalars(select(BriefSource.brief_id).where(BriefSource.source_item_id == source_id)).all())
    session.execute(delete(BriefCitation).where(or_(BriefCitation.source_item_id == source_id, BriefCitation.content_chunk_id.in_(chunk_ids or [uuid.uuid4()]))))
    session.execute(delete(BriefSource).where(BriefSource.source_item_id == source_id))
    session.execute(delete(TopicSynthesisCitation).where(or_(TopicSynthesisCitation.source_item_id == source_id, TopicSynthesisCitation.content_chunk_id.in_(chunk_ids or [uuid.uuid4()]))))
    session.execute(delete(TopicSynthesisSource).where(TopicSynthesisSource.source_item_id == source_id))
    session.execute(delete(AskCitation).where(or_(AskCitation.source_item_id == source_id, AskCitation.content_chunk_id.in_(chunk_ids or [uuid.uuid4()]))))
    session.execute(delete(IndexingRun).where(IndexingRun.source_item_id == source_id))

    session.execute(delete(ProjectSource).where(ProjectSource.source_item_id == source_id))
    candidates = list(session.scalars(select(ProjectCandidate).where(ProjectCandidate.source_item_id == source_id)).all())
    for candidate in candidates:
        session.execute(delete(Project).where(Project.origin_project_candidate_id == candidate.id))
        session.execute(delete(ProjectCandidateClaim).where(ProjectCandidateClaim.project_candidate_id == candidate.id))
        session.execute(delete(ProjectCandidate).where(ProjectCandidate.id == candidate.id))

    cards = list(session.scalars(select(KnowledgeCard).where(KnowledgeCard.source_item_id == source_id)).all())
    for card in cards:
        session.execute(delete(KnowledgeCardClaim).where(KnowledgeCardClaim.knowledge_card_id == card.id))
        session.execute(delete(KnowledgeCard).where(KnowledgeCard.id == card.id))
    insights = list(session.scalars(select(CommercialInsight).where(CommercialInsight.source_item_id == source_id)).all())
    for insight in insights:
        session.execute(delete(CommercialInsightEntity).where(CommercialInsightEntity.commercial_insight_id == insight.id))
        session.execute(delete(CommercialInsightClaim).where(CommercialInsightClaim.commercial_insight_id == insight.id))
        session.execute(delete(CommercialInsight).where(CommercialInsight.id == insight.id))
    session.execute(delete(EntityMention).where(or_(EntityMention.source_item_id == source_id, EntityMention.content_chunk_id.in_(chunk_ids or [uuid.uuid4()]))))
    session.execute(delete(SourceTopicAssignment).where(SourceTopicAssignment.source_item_id == source_id))
    session.execute(delete(SourceCategoryAssignment).where(SourceCategoryAssignment.source_item_id == source_id))
    session.execute(delete(SourceTag).where(SourceTag.source_item_id == source_id))
    session.execute(delete(OrganizationRun).where(OrganizationRun.source_item_id == source_id))

    runs = list(session.scalars(select(AnalysisRun).where(AnalysisRun.source_item_id == source_id)).all())
    for run in runs:
        result = session.scalar(select(AnalysisResult).where(AnalysisResult.analysis_run_id == run.id))
        if result is not None:
            claim_ids = list(session.scalars(select(Claim.id).where(Claim.analysis_result_id == result.id)).all())
            if claim_ids:
                session.execute(delete(Evidence).where(Evidence.claim_id.in_(claim_ids)))
                session.execute(delete(Claim).where(Claim.id.in_(claim_ids)))
            session.execute(delete(AnalysisResult).where(AnalysisResult.id == result.id))
    if chunk_ids:
        session.execute(delete(Evidence).where(Evidence.content_chunk_id.in_(chunk_ids)))
        session.execute(delete(ChunkEmbedding).where(ChunkEmbedding.content_chunk_id.in_(chunk_ids)))
    session.execute(delete(AnalysisRun).where(AnalysisRun.source_item_id == source_id))
    if chunk_ids:
        session.execute(delete(ContentChunk).where(ContentChunk.id.in_(chunk_ids)))
    if document_ids:
        session.execute(delete(ExtractedDocument).where(ExtractedDocument.id.in_(document_ids)))
    session.execute(delete(ExtractionRun).where(ExtractionRun.source_item_id == source_id))

    session.execute(delete(SourceRelation).where(or_(SourceRelation.from_source_id == source_id, SourceRelation.to_source_id == source_id)))
    session.execute(delete(OriginalSourceCandidate).where(OriginalSourceCandidate.source_item_id == source_id))
    session.execute(delete(SourceDiscoveryRun).where(SourceDiscoveryRun.source_item_id == source_id))
    assets = list(session.scalars(select(SourceAsset).where(SourceAsset.source_item_id == source_id)).all())
    for asset in assets:
        _remove_owned_file(asset.stored_path)
    session.execute(delete(SourceAsset).where(SourceAsset.source_item_id == source_id))
    session.execute(delete(IngestionRecord).where(IngestionRecord.source_item_id == source_id))
    session.delete(source)
    session.flush()

    empty_brief_ids = []
    for brief_id in brief_ids:
        remaining = session.scalar(select(func.count()).select_from(BriefSource).where(BriefSource.brief_id == brief_id))
        if remaining == 0:
            empty_brief_ids.append(brief_id)
    if empty_brief_ids:
        session.execute(delete(BriefCitation).where(BriefCitation.brief_id.in_(empty_brief_ids)))
        session.execute(update(Brief).where(Brief.regenerated_from_id.in_(empty_brief_ids)).values(regenerated_from_id=None))
        session.execute(delete(Brief).where(Brief.id.in_(empty_brief_ids)))


def _remove_owned_file(stored_path: str) -> None:
    try:
        path = Path(stored_path).resolve()
    except OSError:
        return
    if path == _DATA_ROOT or _DATA_ROOT not in path.parents:
        return
    if path.is_file():
        path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("markers", nargs="*")
    parser.add_argument("--topic", action="append", default=[])
    args = parser.parse_args()
    session = get_sessionmaker()()
    try:
        if args.markers:
            purge_markers(session, args.markers, commit=False)
        for name in args.topic:
            purge_topic(session, name, commit=False)
        session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    main()
