"""ORM models. Importing this package registers M1 tables on Base.metadata."""

from app.models.analysis import (
    AnalysisResult,
    AnalysisRun,
    Claim,
    Evidence,
    LLMModelDeployment,
    LLMProviderConfig,
    LLMProviderCredential,
    LLMWorkflowRoute,
)
from app.models.cover import CoverGenerationRun, CoverPromptRevision, SourceCoverAsset
from app.models.organization import Category, OrganizationRun
from app.models.discovery import OriginalSourceCandidate, SourceDiscoveryRun, SourceRelation
from app.models.enums import (
    CandidateStatus,
    ConfirmedBy,
    DiscoveryStatus,
    DuplicateReason,
    IngestionOrigin,
    IngestionStatus,
    IngestionType,
    RelationType,
    SourceType,
)
from app.models.extraction import ContentChunk, ExtractedDocument, ExtractionRun
from app.models.ingestion_record import IngestionRecord
from app.models.retrieval import AskCitation, AskSession, AskTurn, ChunkEmbedding, EmbeddingProfile, EmbeddingProviderConfig, IndexingRun
from app.models.synthesis import Brief, BriefCitation, BriefSource, TopicSynthesis
from app.models.source_asset import SourceAsset
from app.models.source_item import SourceItem

__all__ = [
    "AnalysisResult",
    "AnalysisRun",
    "CandidateStatus",
    "Claim",
    "Evidence",
    "CoverGenerationRun",
    "CoverPromptRevision",
    "LLMModelDeployment",
    "LLMProviderConfig",
    "LLMProviderCredential",
    "LLMWorkflowRoute",
    "SourceCoverAsset",
    "ConfirmedBy",
    "ContentChunk",
    "DiscoveryStatus",
    "DuplicateReason",
    "ExtractedDocument",
    "ExtractionRun",
    "IngestionOrigin",
    "IngestionRecord",
    "IngestionStatus",
    "IngestionType",
    "OriginalSourceCandidate",
    "RelationType",
    "SourceAsset",
    "SourceDiscoveryRun",
    "SourceItem",
    "SourceRelation",
    "SourceType",
]
