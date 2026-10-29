import hashlib
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.analysis import AnalysisResult, Claim, Evidence
from app.models.extraction import ContentChunk
from app.models.discovery import SourceRelation
from app.models.organization import Topic
from app.models.retrieval import ChunkEmbedding
from app.models.source_asset import SourceAsset
from app.models.source_item import SourceItem
from app.models.synthesis import BriefCitation
from app.services.retrieval.constants import EMBEDDING_DIMENSIONS


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_storage(session: Session, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    missing = []
    corrupt = []
    registered = set()
    raw_root = settings.raw_storage_path().resolve()
    for asset in session.scalars(select(SourceAsset)):
        stored_path = Path(asset.stored_path)
        path = stored_path if stored_path.is_absolute() else raw_root / stored_path
        path = path.resolve()
        registered.add(path)
        if not path.is_file():
            missing.append({"asset_id": str(asset.id), "source_id": str(asset.source_item_id)})
            continue
        if path.stat().st_size != asset.size_bytes or _sha256(path) != asset.sha256:
            corrupt.append({"asset_id": str(asset.id), "source_id": str(asset.source_item_id)})
    orphans = []
    if settings.raw_storage_path().exists():
        for path in settings.raw_storage_path().rglob("*"):
            if path.is_file() and path.name != ".gitkeep" and path.resolve() not in registered:
                orphans.append(str(path))
    counts = {"missing": len(missing), "corrupt": len(corrupt), "orphan": len(orphans)}
    return {"status": "PASS" if not missing and not corrupt else "FAIL", "counts": counts, "missing": missing, "corrupt": corrupt, "orphan": orphans[:20]}


def audit_data(session: Session) -> dict:
    issues = {}
    evidence_bad = session.scalar(
        select(func.count()).select_from(Evidence).where(~Evidence.content_chunk_id.in_(select(ContentChunk.id)))
    )
    claim_bad = session.scalar(select(func.count()).select_from(Claim).where(~Claim.analysis_result_id.in_(select(AnalysisResult.id))))
    citation_bad = session.scalar(
        select(func.count()).select_from(BriefCitation).where(
            (~BriefCitation.source_item_id.in_(select(SourceItem.id)))
            | (BriefCitation.content_chunk_id.is_not(None) & ~BriefCitation.content_chunk_id.in_(select(ContentChunk.id)))
            | (BriefCitation.claim_id.is_not(None) & ~BriefCitation.claim_id.in_(select(Claim.id)))
        )
    )
    relation_bad = session.scalar(
        select(func.count()).select_from(SourceRelation).where(
            (~SourceRelation.from_source_id.in_(select(SourceItem.id))) | (~SourceRelation.to_source_id.in_(select(SourceItem.id)))
        )
    )
    current_duplicates = session.execute(
        text(
            """
            SELECT count(*) FROM (
              SELECT source_item_id FROM analysis_runs WHERE is_current
              GROUP BY source_item_id HAVING count(*) > 1
            ) duplicates
            """
        )
    ).scalar_one()
    embedding_bad = session.scalar(select(func.count()).select_from(ChunkEmbedding).where(ChunkEmbedding.dimensions != EMBEDDING_DIMENSIONS))
    primary_duplicates = session.execute(
        text(
            """
            SELECT count(*) FROM (
              SELECT source_item_id FROM source_category_assignments WHERE is_primary
              GROUP BY source_item_id HAVING count(*) > 1
            ) duplicates
            """
        )
    ).scalar_one()
    merged_inconsistent = session.scalar(
        select(func.count()).select_from(Topic).where(Topic.merged_into_topic_id.is_not(None), ~Topic.merged_into_topic_id.in_(select(Topic.id)))
    )
    issues = {
        "evidence": int(evidence_bad or 0),
        "claim": int(claim_bad or 0),
        "brief_citation": int(citation_bad or 0),
        "source_relation": int(relation_bad or 0),
        "current_run": int(current_duplicates or 0),
        "embedding_dimensions": int(embedding_bad or 0),
        "primary_category": int(primary_duplicates or 0),
        "merged_topic": int(merged_inconsistent or 0),
    }
    return {"status": "PASS" if not any(issues.values()) else "FAIL", "counts": issues}
