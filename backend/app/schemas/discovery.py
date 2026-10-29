import uuid
from datetime import datetime

from pydantic import BaseModel


class ManualCandidateRequest(BaseModel):
    url: str


class CandidateView(BaseModel):
    id: uuid.UUID
    candidate_url: str
    normalized_candidate_url: str
    title: str | None
    author: str | None
    publisher: str | None
    candidate_type: str
    score: float
    confidence: float
    match_reasons: list
    evidence: dict
    rank: int
    status: str
    previously_rejected: bool
    likely_original: bool


class RelationView(BaseModel):
    id: uuid.UUID
    from_source_id: uuid.UUID
    to_source_id: uuid.UUID
    relation_type: str
    confirmed_by: str
    candidate_id: uuid.UUID | None
    created_at: datetime


class DiscoveryRunView(BaseModel):
    id: uuid.UUID
    source_item_id: uuid.UUID
    status: str
    resolver_type: str
    resolver_version: str
    query_summary: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime


class DiscoveryView(BaseModel):
    run: DiscoveryRunView | None
    candidates: list[CandidateView]
    relations: list[RelationView]


class ConfirmResponse(BaseModel):
    candidate: CandidateView
    relation: RelationView
    target_source_id: uuid.UUID
    target_source_type: str
    target_canonical_url: str | None
