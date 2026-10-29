import uuid

from fastapi import APIRouter, Depends

from app.api.deps import get_discovery_service
from app.models.discovery import OriginalSourceCandidate, SourceDiscoveryRun, SourceRelation
from app.schemas.discovery import (
    CandidateView,
    ConfirmResponse,
    DiscoveryRunView,
    DiscoveryView,
    ManualCandidateRequest,
    RelationView,
)
from app.services.discovery.service import DiscoveryService

router = APIRouter(prefix="/api", tags=["discovery"])


def _candidate(row: OriginalSourceCandidate) -> CandidateView:
    evidence = row.evidence_json or {}
    return CandidateView(
        id=row.id,
        candidate_url=row.candidate_url,
        normalized_candidate_url=row.normalized_candidate_url,
        title=row.title,
        author=row.author,
        publisher=row.publisher,
        candidate_type=row.candidate_type,
        score=row.score,
        confidence=row.confidence,
        match_reasons=list(row.match_reasons_json or []),
        evidence=evidence,
        rank=row.rank,
        status=row.status,
        previously_rejected=bool(evidence.get("previously_rejected")),
        likely_original=bool(evidence.get("likely_original")),
    )


def _relation(row: SourceRelation) -> RelationView:
    return RelationView(
        id=row.id,
        from_source_id=row.from_source_id,
        to_source_id=row.to_source_id,
        relation_type=row.relation_type,
        confirmed_by=row.confirmed_by,
        candidate_id=row.candidate_id,
        created_at=row.created_at,
    )


def _run(row: SourceDiscoveryRun | None) -> DiscoveryRunView | None:
    if row is None:
        return None
    return DiscoveryRunView(
        id=row.id,
        source_item_id=row.source_item_id,
        status=row.status,
        resolver_type=row.resolver_type,
        resolver_version=row.resolver_version,
        query_summary=row.query_summary,
        error_code=row.error_code,
        error_message=row.error_message,
        created_at=row.created_at,
    )


@router.post("/sources/{source_id}/discover", response_model=DiscoveryRunView)
def discover(source_id: uuid.UUID, service: DiscoveryService = Depends(get_discovery_service)) -> DiscoveryRunView:
    return _run(service.start(source_id))


@router.post("/sources/{source_id}/rediscover", response_model=DiscoveryRunView)
def rediscover(source_id: uuid.UUID, service: DiscoveryService = Depends(get_discovery_service)) -> DiscoveryRunView:
    return _run(service.start(source_id))


@router.get("/sources/{source_id}/discovery", response_model=DiscoveryView)
def get_discovery(source_id: uuid.UUID, service: DiscoveryService = Depends(get_discovery_service)) -> DiscoveryView:
    run, candidates, relations = service.current(source_id)
    return DiscoveryView(run=_run(run), candidates=[_candidate(row) for row in candidates], relations=[_relation(row) for row in relations])


@router.post("/sources/{source_id}/discovery/candidates", response_model=CandidateView)
def add_manual_candidate(
    source_id: uuid.UUID,
    body: ManualCandidateRequest,
    service: DiscoveryService = Depends(get_discovery_service),
) -> CandidateView:
    return _candidate(service.add_manual(source_id, body.url))


@router.post("/source-candidates/{candidate_id}/confirm", response_model=ConfirmResponse)
def confirm_candidate(candidate_id: uuid.UUID, service: DiscoveryService = Depends(get_discovery_service)) -> ConfirmResponse:
    candidate, relation, target = service.confirm(candidate_id)
    return ConfirmResponse(
        candidate=_candidate(candidate),
        relation=_relation(relation),
        target_source_id=target.id,
        target_source_type=target.source_type,
        target_canonical_url=target.canonical_url,
    )


@router.post("/source-candidates/{candidate_id}/reject", response_model=CandidateView)
def reject_candidate(candidate_id: uuid.UUID, service: DiscoveryService = Depends(get_discovery_service)) -> CandidateView:
    return _candidate(service.reject(candidate_id))
