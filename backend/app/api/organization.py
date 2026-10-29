import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_organization_service
from app.db.session import get_db
from app.models.analysis import AnalysisResult, AnalysisRun, Claim, Evidence
from app.models.ingestion_record import IngestionRecord
from app.models.organization import (
    Category,
    CommercialInsight,
    CommercialInsightClaim,
    CommercialInsightEntity,
    Entity,
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
    Tag,
    Topic,
)
from app.models.source_item import SourceItem
from app.services.organization.service import OrganizationService
from app.services.extraction.x_tweet import is_x_status_url

router = APIRouter(prefix="/api", tags=["organization"])


def _trusted_user_analysis_clause():
    """Exclude simulated analysis artifacts from USER-facing organization views."""
    from sqlalchemy import or_

    return or_(SourceItem.system_scope != "USER", AnalysisRun.provider_type != "FAKE", AnalysisRun.model_name != "fake-model")


def _is_untrusted_user_analysis(session: Session, analysis_run_id: uuid.UUID | None) -> bool:
    if analysis_run_id is None:
        return False
    row = session.execute(
        select(SourceItem.system_scope, AnalysisRun.provider_type, AnalysisRun.model_name)
        .join(AnalysisRun, AnalysisRun.source_item_id == SourceItem.id)
        .where(AnalysisRun.id == analysis_run_id)
    ).first()
    return bool(row and row.system_scope == "USER" and (row.provider_type == "FAKE" or row.model_name == "fake-model"))


def _is_untrusted_artifact(session: Session, analysis_result_id: uuid.UUID | None) -> bool:
    result = session.get(AnalysisResult, analysis_result_id) if analysis_result_id else None
    return bool(result and _is_untrusted_user_analysis(session, result.analysis_run_id))


class CategoryBody(BaseModel):
    name: str
    description: str | None = None
    display_order: int = 0
    is_active: bool | None = None


class CategoryEdit(BaseModel):
    add: list[str] = []
    reject: list[str] = []
    primary: str | None = None


class TopicEdit(BaseModel):
    add: list[str] = []
    reject_ids: list[uuid.UUID] = []


class TagEdit(BaseModel):
    add: list[str] = []
    remove: list[str] = []


class MergeBody(BaseModel):
    canonical_id: uuid.UUID


class AliasBody(BaseModel):
    alias: str


class ParentBody(BaseModel):
    parent_id: uuid.UUID | None = None


def _claims(session: Session, link_model, owner_field: str, owner_id: uuid.UUID) -> list[dict]:
    links = list(session.scalars(select(link_model).where(getattr(link_model, owner_field) == owner_id).order_by(link_model.display_order)).all())
    rows = []
    for link in links:
        claim = session.get(Claim, link.claim_id)
        if claim is None:
            continue
        evidence = list(session.scalars(select(Evidence).where(Evidence.claim_id == claim.id)).all())
        rows.append(
            {
                "claim_id": claim.id,
                "claim_type": claim.claim_type,
                "role": link.role,
                "text": claim.text,
                "evidence": [{"id": item.id, "content_chunk_id": item.content_chunk_id, "quote_text": item.quote_text} for item in evidence],
            }
        )
    return rows


@router.post("/sources/{source_id}/organize")
@router.post("/sources/{source_id}/reorganize")
def organize(source_id: uuid.UUID, service: OrganizationService = Depends(get_organization_service)):
    run = service.organize(source_id)
    return {"id": run.id, "status": run.status, "analysis_run_id": run.analysis_run_id, "is_current": run.is_current}


@router.get("/sources/{source_id}/organization")
def organization(source_id: uuid.UUID, session: Session = Depends(get_db), service: OrganizationService = Depends(get_organization_service)):
    service.ensure_default_categories()
    run = session.scalar(select(OrganizationRun).where(OrganizationRun.source_item_id == source_id, OrganizationRun.is_current.is_(True)))
    categories = []
    for row in session.scalars(select(SourceCategoryAssignment).where(SourceCategoryAssignment.source_item_id == source_id, SourceCategoryAssignment.status == "ACTIVE")):
        if row.origin == "SYSTEM_ANALYSIS" and _is_untrusted_user_analysis(session, row.analysis_run_id):
            continue
        if run is not None and row.origin == "SYSTEM_ANALYSIS" and row.organization_run_id != run.id:
            continue
        category = session.get(Category, row.category_id)
        if category:
            categories.append({"slug": category.slug, "name": category.name, "origin": row.origin, "is_primary": row.is_primary, "reason": row.reason, "confidence": row.confidence})
    topics = []
    for row in session.scalars(select(SourceTopicAssignment).where(SourceTopicAssignment.source_item_id == source_id, SourceTopicAssignment.status == "ACTIVE")):
        if row.origin == "SYSTEM_ANALYSIS" and _is_untrusted_user_analysis(session, row.analysis_run_id):
            continue
        if run is not None and row.origin == "SYSTEM_ANALYSIS" and row.organization_run_id != run.id:
            continue
        topic = session.get(Topic, row.topic_id)
        if topic and topic.merged_into_topic_id is None:
            topics.append({"id": topic.id, "name": topic.name, "origin": row.origin})
    entities = [{"id": item.id, "name": item.name, "entity_type": item.entity_type} for item in session.scalars(select(Entity).join(EntityMention, EntityMention.entity_id == Entity.id).join(SourceItem, SourceItem.id == EntityMention.source_item_id).join(AnalysisRun, AnalysisRun.id == EntityMention.analysis_run_id).where(EntityMention.source_item_id == source_id, Entity.merged_into_entity_id.is_(None), _trusted_user_analysis_clause())).unique()]
    tags = [session.get(Tag, row.tag_id).name for row in session.scalars(select(SourceTag).where(SourceTag.source_item_id == source_id)) if session.get(Tag, row.tag_id)]
    card = session.scalar(select(KnowledgeCard).where(KnowledgeCard.source_item_id == source_id, KnowledgeCard.is_current.is_(True)))
    insight = session.scalar(select(CommercialInsight).where(CommercialInsight.source_item_id == source_id, CommercialInsight.is_current.is_(True)))
    candidate = session.scalar(select(ProjectCandidate).where(ProjectCandidate.source_item_id == source_id).order_by(ProjectCandidate.created_at.desc()))
    if run is not None and _is_untrusted_user_analysis(session, run.analysis_run_id):
        card = insight = candidate = None
    user_collection = session.scalar(select(IngestionRecord.id).where(IngestionRecord.source_item_id == source_id, IngestionRecord.origin == "USER_COLLECTION"))
    return {
        "run": None if run is None else {"id": run.id, "status": run.status, "analysis_run_id": run.analysis_run_id},
        "categories": categories,
        "topics": topics,
        "entities": entities,
        "tags": tags,
        "knowledge_card_id": None if card is None else card.id,
        "commercial_insight_id": None if insight is None else insight.id,
        "project_candidate_id": None if candidate is None else candidate.id,
        "project_candidate_status": None if candidate is None else candidate.status,
        "collection_origin": "USER_COLLECTION" if user_collection else "SYSTEM_DISCOVERY",
    }


@router.get("/categories")
def list_categories(session: Session = Depends(get_db), service: OrganizationService = Depends(get_organization_service)):
    service.ensure_default_categories()
    session.commit()
    rows = session.scalars(select(Category).where(Category.is_active.is_(True)).order_by(Category.display_order)).all()
    return [{"id": row.id, "name": row.name, "slug": row.slug, "description": row.description, "display_order": row.display_order, "is_system_default": row.is_system_default} for row in rows]


@router.post("/categories")
def create_category(body: CategoryBody, service: OrganizationService = Depends(get_organization_service)):
    row = service.create_category(body.name, body.description, body.display_order)
    return {"id": row.id, "slug": row.slug, "name": row.name}


@router.put("/categories/{category_id}")
def update_category(category_id: uuid.UUID, body: CategoryBody, service: OrganizationService = Depends(get_organization_service)):
    row = service.update_category(category_id, name=body.name, description=body.description, display_order=body.display_order, is_active=body.is_active)
    return {"id": row.id, "slug": row.slug, "is_active": row.is_active}


@router.put("/sources/{source_id}/categories")
def edit_categories(source_id: uuid.UUID, body: CategoryEdit, service: OrganizationService = Depends(get_organization_service)):
    service.set_categories(source_id, add=body.add, reject=body.reject, primary=body.primary)
    return {"ok": True}


@router.put("/sources/{source_id}/topics")
def edit_topics(source_id: uuid.UUID, body: TopicEdit, service: OrganizationService = Depends(get_organization_service)):
    service.set_topics(source_id, add=body.add, reject_ids=body.reject_ids)
    return {"ok": True}


@router.put("/sources/{source_id}/tags")
def edit_tags(source_id: uuid.UUID, body: TagEdit, service: OrganizationService = Depends(get_organization_service)):
    service.set_tags(source_id, add=body.add, remove=body.remove)
    return {"ok": True}


@router.get("/topics")
def list_topics(session: Session = Depends(get_db)):
    rows = session.scalars(select(Topic).where(Topic.merged_into_topic_id.is_(None)).order_by(Topic.name)).all()
    return [{"id": row.id, "name": row.name, "parent_id": row.parent_id, "source_count": session.scalar(select(func.count()).select_from(SourceTopicAssignment).join(SourceItem, SourceItem.id == SourceTopicAssignment.source_item_id).outerjoin(AnalysisRun, AnalysisRun.id == SourceTopicAssignment.analysis_run_id).where(SourceTopicAssignment.topic_id == row.id, SourceTopicAssignment.status == "ACTIVE", (SourceTopicAssignment.origin == "USER") | _trusted_user_analysis_clause()))} for row in rows]


@router.get("/topics/{topic_id}")
def topic_detail(topic_id: uuid.UUID, session: Session = Depends(get_db)):
    topic = session.get(Topic, topic_id)
    if topic is None:
        return {"error": "TOPIC_NOT_FOUND"}
    source_ids = list(session.scalars(select(SourceTopicAssignment.source_item_id).join(SourceItem, SourceItem.id == SourceTopicAssignment.source_item_id).outerjoin(AnalysisRun, AnalysisRun.id == SourceTopicAssignment.analysis_run_id).where(SourceTopicAssignment.topic_id == topic_id, SourceTopicAssignment.status == "ACTIVE", (SourceTopicAssignment.origin == "USER") | _trusted_user_analysis_clause())))
    return {
        "id": topic.id,
        "name": topic.name,
        "merged_into_topic_id": topic.merged_into_topic_id,
        "sources": [{"id": item, "display_name": session.get(SourceItem, item).display_name if session.get(SourceItem, item) else None} for item in source_ids],
        "knowledge_cards": [row.id for row in session.scalars(select(KnowledgeCard).where(KnowledgeCard.source_item_id.in_(source_ids or [uuid.uuid4()]), KnowledgeCard.is_current.is_(True)))],
        "entities": [],
    }


@router.post("/topics")
def create_topic(body: AliasBody, session: Session = Depends(get_db), service: OrganizationService = Depends(get_organization_service)):
    topic = service._find_or_create_topic(body.alias, allow_create=True)
    if topic is None:
        from app.services.organization.service import OrganizationError

        raise OrganizationError(400, "INVALID_TOPIC", "主题名称不可用。")
    session.commit()
    return {"id": topic.id, "name": topic.name}


@router.post("/topics/{topic_id}/merge")
def merge_topic(topic_id: uuid.UUID, body: MergeBody, service: OrganizationService = Depends(get_organization_service)):
    canonical = service.merge_topics(topic_id, body.canonical_id)
    return {"id": canonical.id, "name": canonical.name}


@router.post("/topics/{topic_id}/alias")
def topic_alias(topic_id: uuid.UUID, body: AliasBody, service: OrganizationService = Depends(get_organization_service)):
    service.add_alias("topic", topic_id, body.alias)
    return {"ok": True}


@router.put("/topics/{topic_id}/parent")
def topic_parent(topic_id: uuid.UUID, body: ParentBody, service: OrganizationService = Depends(get_organization_service)):
    topic = service.set_topic_parent(topic_id, body.parent_id)
    return {"id": topic.id, "parent_id": topic.parent_id}


@router.get("/entities")
def list_entities(entity_type: str | None = None, session: Session = Depends(get_db)):
    query = select(Entity).where(Entity.merged_into_entity_id.is_(None))
    if entity_type:
        query = query.where(Entity.entity_type == entity_type.upper())
    return [{"id": row.id, "name": row.name, "entity_type": row.entity_type} for row in session.scalars(query.order_by(Entity.name))]


@router.get("/entities/{entity_id}")
def entity_detail(entity_id: uuid.UUID, session: Session = Depends(get_db)):
    entity = session.get(Entity, entity_id)
    if entity is None:
        return {"error": "ENTITY_NOT_FOUND"}
    source_ids = list(session.scalars(select(EntityMention.source_item_id).join(SourceItem, SourceItem.id == EntityMention.source_item_id).join(AnalysisRun, AnalysisRun.id == EntityMention.analysis_run_id).where(EntityMention.entity_id == entity_id, _trusted_user_analysis_clause())))
    return {"id": entity.id, "name": entity.name, "entity_type": entity.entity_type, "merged_into_entity_id": entity.merged_into_entity_id, "sources": source_ids}


@router.post("/entities/{entity_id}/merge")
def merge_entity(entity_id: uuid.UUID, body: MergeBody, service: OrganizationService = Depends(get_organization_service)):
    canonical = service.merge_entities(entity_id, body.canonical_id)
    return {"id": canonical.id, "name": canonical.name}


@router.post("/entities/{entity_id}/alias")
def entity_alias(entity_id: uuid.UUID, body: AliasBody, service: OrganizationService = Depends(get_organization_service)):
    service.add_alias("entity", entity_id, body.alias)
    return {"ok": True}


@router.get("/sources/{source_id}/cover-image")
def source_cover_image(source_id: uuid.UUID, asset_id: uuid.UUID | None = None, session: Session = Depends(get_db)):
    from app.models.extraction import ExtractedDocument
    from app.models.cover import SourceCoverAsset
    from app.services.cover.resolution import resolve_cover
    from app.services.cover.storage import CoverStorageError, read_cover_file
    from app.services.cover.verification import verify_asset_file
    from app.services.library_cover_fetch import CoverFetchError, fetch_cover_bytes
    from app.services.system_scope import scope_visible_for_api

    source = session.get(SourceItem, source_id)
    if source is None or not scope_visible_for_api(source.system_scope):
        raise HTTPException(status_code=404, detail="找不到资料。")
    if asset_id is not None:
        asset = session.scalar(
            select(SourceCoverAsset).where(
                SourceCoverAsset.id == asset_id,
                SourceCoverAsset.source_item_id == source_id,
                SourceCoverAsset.kind == "GENERATED",
            )
        )
        if asset is None:
            raise HTTPException(status_code=404, detail="找不到候选封面。")
        ok, error = verify_asset_file(asset.relative_path)
        if not ok:
            raise HTTPException(status_code=404, detail=error or "候选封面不可用。")
        try:
            body, media_type = read_cover_file(asset.relative_path)
        except CoverStorageError as exc:
            raise HTTPException(status_code=404, detail=exc.message) from exc
        return Response(
            content=body,
            media_type=media_type,
            headers={"Cache-Control": "private, max-age=31536000, immutable"},
        )
    doc = session.scalar(
        select(ExtractedDocument)
        .where(ExtractedDocument.source_item_id == source.id)
        .order_by(ExtractedDocument.created_at.desc())
    )
    resolved = resolve_cover(session, source.id, doc)
    if resolved is None:
        raise HTTPException(status_code=404, detail="没有可用封面。")
    if resolved.relative_path:
        try:
            body, media_type = read_cover_file(resolved.relative_path)
        except CoverStorageError as exc:
            raise HTTPException(status_code=404, detail=exc.message) from exc
        return Response(content=body, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})
    if resolved.remote_url:
        try:
            body, media_type = fetch_cover_bytes(resolved.remote_url)
        except CoverFetchError as exc:
            raise HTTPException(status_code=502, detail=exc.message) from exc
        return Response(content=body, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})
    raise HTTPException(status_code=404, detail="没有可用封面。")


@router.post("/sources/{source_id}/trash")
def trash_source(source_id: uuid.UUID, session: Session = Depends(get_db)) -> dict:
    from app.services.source_lifecycle import SourceLifecycleError, soft_delete_source
    from app.services.system_scope import scope_visible_for_api

    source = session.get(SourceItem, source_id)
    if source is None or not scope_visible_for_api(source.system_scope):
        raise HTTPException(status_code=404, detail="SOURCE_NOT_FOUND")
    try:
        row = soft_delete_source(session, source_id)
    except SourceLifecycleError as exc:
        raise HTTPException(status_code=404, detail=exc.code) from exc
    return {"ok": True, "source_id": row.id, "deleted_at": row.deleted_at}


@router.post("/sources/{source_id}/restore")
def restore_source_item(source_id: uuid.UUID, session: Session = Depends(get_db)) -> dict:
    from app.services.source_lifecycle import SourceLifecycleError, restore_source
    from app.services.system_scope import scope_visible_for_api

    source = session.get(SourceItem, source_id)
    if source is None or not scope_visible_for_api(source.system_scope):
        raise HTTPException(status_code=404, detail="SOURCE_NOT_FOUND")
    try:
        row = restore_source(session, source_id)
    except SourceLifecycleError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message}) from exc
    return {"ok": True, "source_id": row.id}


@router.get("/library/trash")
def library_trash(session: Session = Depends(get_db)) -> dict:
    from app.services.library_preview import library_cover_origin, library_preview_url
    from app.services.source_lifecycle import list_trash_sources
    from app.services.system_scope import api_visibility_filter

    items = list_trash_sources(session, scope_filter=api_visibility_filter(SourceItem.system_scope))
    enriched = []
    for item in items:
        source = session.get(SourceItem, item["source_id"])
        doc = None
        if source is not None:
            from app.models.extraction import ExtractedDocument

            doc = session.scalar(
                select(ExtractedDocument).where(ExtractedDocument.source_item_id == source.id).order_by(ExtractedDocument.created_at.desc())
            )
        enriched.append(
            {
                **item,
                "preview_image_url": None if source is None else library_preview_url(session, source, doc),
                "cover_origin": None if source is None else library_cover_origin(session, source.id, doc),
            }
        )
    return {"items": enriched}


@router.get("/library")
def library(
    category: str | None = None,
    topic_id: uuid.UUID | None = None,
    entity_id: uuid.UUID | None = None,
    tag: str | None = None,
    source_type: str | None = None,
    collected_from: datetime | None = None,
    collected_to: datetime | None = None,
    scope: str = "mine",
    session: Session = Depends(get_db),
):
    from app.models.analysis import AnalysisResult, AnalysisRun
    from app.models.extraction import ExtractedDocument
    from app.services.display_title import library_card_title, resolve_display_title
    from app.services.extraction_status import extraction_status_for_source
    from app.services.library_preview import library_cover_origin, library_cover_status, library_preview_url
    from app.services.research_note import analysis_status_for_source, content_analysis_summary
    from app.services.system_scope import api_visibility_filter

    sources = list(
        session.scalars(
            select(SourceItem)
            .where(api_visibility_filter(SourceItem.system_scope))
            .where(SourceItem.deleted_at.is_(None))
            .order_by(SourceItem.created_at.desc())
        ).all()
    )
    items = []
    for source in sources:
        user_rows = list(session.scalars(select(IngestionRecord).where(IngestionRecord.source_item_id == source.id, IngestionRecord.origin == "USER_COLLECTION", IngestionRecord.status == "STORED")))
        discovered = session.scalar(select(IngestionRecord.id).where(IngestionRecord.source_item_id == source.id, IngestionRecord.origin == "SYSTEM_DISCOVERY"))
        if scope == "mine" and not user_rows:
            continue
        if source_type and source.source_type != source_type:
            continue
        collected = [row.collected_at for row in user_rows]
        first = min(collected) if collected else None
        last = max(collected) if collected else None
        if collected_from and (first is None or first < collected_from):
            continue
        if collected_to and (first is None or first > collected_to):
            continue
        run = session.scalar(select(OrganizationRun).where(OrganizationRun.source_item_id == source.id, OrganizationRun.is_current.is_(True)))
        slugs = []
        for row in session.scalars(select(SourceCategoryAssignment).where(SourceCategoryAssignment.source_item_id == source.id, SourceCategoryAssignment.status == "ACTIVE")):
            if row.origin == "SYSTEM_ANALYSIS" and _is_untrusted_user_analysis(session, row.analysis_run_id):
                continue
            if run is not None and row.origin == "SYSTEM_ANALYSIS" and row.organization_run_id != run.id:
                continue
            category_row = session.get(Category, row.category_id)
            if category_row:
                slugs.append(category_row.slug)
        if category and category not in slugs:
            continue
        if topic_id and session.scalar(select(SourceTopicAssignment.id).join(SourceItem, SourceItem.id == SourceTopicAssignment.source_item_id).outerjoin(AnalysisRun, AnalysisRun.id == SourceTopicAssignment.analysis_run_id).where(SourceTopicAssignment.source_item_id == source.id, SourceTopicAssignment.topic_id == topic_id, SourceTopicAssignment.status == "ACTIVE", ((SourceTopicAssignment.origin == "USER") | _trusted_user_analysis_clause()))) is None:
            continue
        if entity_id and session.scalar(select(EntityMention.id).join(SourceItem, SourceItem.id == EntityMention.source_item_id).join(AnalysisRun, AnalysisRun.id == EntityMention.analysis_run_id).where(EntityMention.source_item_id == source.id, EntityMention.entity_id == entity_id, _trusted_user_analysis_clause())) is None:
            continue
        if tag:
            tag_row = session.scalar(select(Tag).where(Tag.normalized_name == tag.casefold()))
            if tag_row is None or session.scalar(select(SourceTag.id).where(SourceTag.source_item_id == source.id, SourceTag.tag_id == tag_row.id)) is None:
                continue
        doc = session.scalar(select(ExtractedDocument).where(ExtractedDocument.source_item_id == source.id).order_by(ExtractedDocument.created_at.desc()))
        run = session.scalar(select(AnalysisRun).where(AnalysisRun.source_item_id == source.id, AnalysisRun.is_current.is_(True)))
        result = session.scalar(select(AnalysisResult).where(AnalysisResult.analysis_run_id == run.id)) if run else None
        summary = content_analysis_summary(session, source.id) or (result.summary if result else None)
        analysis_status, analysis_status_code = analysis_status_for_source(session, source.id)
        ext = extraction_status_for_source(session, source.id)
        card_title = library_card_title(source, document_title=doc.title if doc else None, analysis_summary=summary)
        items.append(
            {
                "source_id": source.id,
                "display_name": source.display_name,
                "title": card_title,
                "title_full": resolve_display_title(source, document_title=doc.title if doc else None, analysis_summary=summary),
                "source_type": source.source_type,
                "supports_text_supplement": source.source_type == "URL" and is_x_status_url(source.original_url or ""),
                "categories": slugs,
                "first_collected_at": first,
                "last_collected_at": last,
                "collection_count": len(user_rows),
                "collection_origin": "USER_COLLECTION" if user_rows else "SYSTEM_DISCOVERY",
                "discovered": bool(discovered) and not user_rows,
                "analysis_status": analysis_status,
                "analysis_status_code": analysis_status_code,
                "extraction_status_label": ext["extraction_status"],
                "has_usable_content": ext["has_usable_content"],
                "preview_image_url": library_preview_url(session, source, doc),
                "cover_status": library_cover_status(source, doc, session),
                "cover_origin": library_cover_origin(session, source.id, doc),
                "summary_snippet": (summary or "").strip().splitlines()[0][:180] if summary else None,
            }
        )
    return {"items": items}


def _artifact(session: Session, model, link_model, field: str, artifact_id: uuid.UUID):
    row = session.get(model, artifact_id)
    if row is None:
        return None
    if _is_untrusted_artifact(session, row.analysis_result_id):
        return None
    return {
        "id": row.id,
        "source_item_id": row.source_item_id,
        "analysis_result_id": row.analysis_result_id,
        "organization_run_id": row.organization_run_id,
        "title": row.title,
        "summary": row.summary_snapshot,
        "status": getattr(row, "status", None),
        "claims": _claims(session, link_model, field, row.id),
        "missing_note": "当前资料未提供。未形成可靠信息 / 待进一步研究。",
    }


@router.get("/knowledge-cards/{card_id}")
def knowledge_card(card_id: uuid.UUID, session: Session = Depends(get_db)):
    return _artifact(session, KnowledgeCard, KnowledgeCardClaim, "knowledge_card_id", card_id)


@router.get("/commercial-insights/{insight_id}")
def commercial_insight(insight_id: uuid.UUID, session: Session = Depends(get_db)):
    payload = _artifact(session, CommercialInsight, CommercialInsightClaim, "commercial_insight_id", insight_id)
    if payload is None:
        return None
    payload["entities"] = [session.get(Entity, row.entity_id).name for row in session.scalars(select(CommercialInsightEntity).where(CommercialInsightEntity.commercial_insight_id == insight_id)) if session.get(Entity, row.entity_id)]
    return payload


@router.get("/project-candidates")
def project_candidates(session: Session = Depends(get_db)):
    rows = session.scalars(select(ProjectCandidate).order_by(ProjectCandidate.created_at.desc()))
    return [
        {"id": row.id, "title": row.title, "status": row.status, "source_item_id": row.source_item_id, "summary": row.summary_snapshot}
        for row in rows
        if not _is_untrusted_artifact(session, row.analysis_result_id)
    ]


@router.get("/project-candidates/{candidate_id}")
def project_candidate(candidate_id: uuid.UUID, session: Session = Depends(get_db)):
    return _artifact(session, ProjectCandidate, ProjectCandidateClaim, "project_candidate_id", candidate_id)


@router.post("/project-candidates/{candidate_id}/reject")
def reject_candidate(candidate_id: uuid.UUID, service: OrganizationService = Depends(get_organization_service)):
    row = service.reject_candidate(candidate_id)
    return {"id": row.id, "status": row.status}


@router.post("/project-candidates/{candidate_id}/promote")
def promote_candidate(candidate_id: uuid.UUID, service: OrganizationService = Depends(get_organization_service)):
    project = service.promote_candidate(candidate_id)
    return {"id": project.id, "name": project.name, "status": project.status}


@router.get("/projects")
def projects(session: Session = Depends(get_db)):
    return [{"id": row.id, "name": row.name, "status": row.status, "description": row.description} for row in session.scalars(select(Project).order_by(Project.created_at.desc()))]


@router.get("/projects/{project_id}")
def project_detail(project_id: uuid.UUID, session: Session = Depends(get_db)):
    row = session.get(Project, project_id)
    if row is None:
        return None
    sources = list(session.scalars(select(ProjectSource.source_item_id).where(ProjectSource.project_id == project_id)))
    claims = []
    if row.origin_project_candidate_id:
        claims = _claims(session, ProjectCandidateClaim, "project_candidate_id", row.origin_project_candidate_id)
    return {"id": row.id, "name": row.name, "status": row.status, "description": row.description, "sources": sources, "claims": claims}
