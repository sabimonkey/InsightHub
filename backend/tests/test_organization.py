import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.models.analysis import AnalysisRun, Claim, Evidence
from app.models.extraction import ContentChunk
from app.models.ingestion_record import IngestionRecord
from app.models.organization import (
    Category,
    CommercialInsight,
    CommercialInsightClaim,
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
    SourceTopicAssignment,
    Topic,
)
from app.models.source_item import SourceItem
from app.services.organization.normalize import normalize_taxonomy_name
from app.services.organization.service import OrganizationService
from tests.test_analysis import _chunk, _payload, _prepare, _service, _settings
from app.services.llm.provider import FakeLLMProvider


def _organize(db_session, created, payload: str | None = None) -> OrganizationRun:
    chunk = _chunk(db_session, created.source_item.id)
    quote = chunk.content.splitlines()[0][:180]
    script = payload or _payload(str(chunk.id), quote)
    _service(db_session, _settings(), FakeLLMProvider(script=[script])).start(created.source_item.id)
    run = db_session.scalar(select(OrganizationRun).where(OrganizationRun.source_item_id == created.source_item.id, OrganizationRun.is_current.is_(True)))
    assert run is not None
    return run


def _json(chunk_id: str, quote: str, categories, topics=None, entities=None):
    body = json.loads(_payload(chunk_id, quote))
    body["category_candidates"] = categories
    body["topic_candidates"] = topics or []
    body["entities"] = entities or []
    return json.dumps(body, ensure_ascii=False)


def test_default_categories_and_custom(db_session):
    service = OrganizationService(db_session, threshold=0.7)
    service.ensure_default_categories()
    slugs = {row.slug for row in db_session.scalars(select(Category))}
    assert {"project_discovery", "business", "knowledge", "other"} <= slugs
    created = service.create_category("研究笔记", None, 9)
    assert created.is_system_default is False
    try:
        service.update_category(db_session.scalar(select(Category).where(Category.slug == "knowledge")).id, name=None, description=None, display_order=None, is_active=False)
        assert False
    except Exception as exc:
        assert exc.code == "SYSTEM_CATEGORY_PROTECTED"


def test_knowledge_card_reuses_claim_evidence(db_session, raw_root, tmp_path):
    created = _prepare(db_session, raw_root, tmp_path, "recorded fact sentence")
    _organize(db_session, created)
    card = db_session.scalar(select(KnowledgeCard).where(KnowledgeCard.source_item_id == created.source_item.id, KnowledgeCard.is_current.is_(True)))
    link = db_session.scalar(select(KnowledgeCardClaim).where(KnowledgeCardClaim.knowledge_card_id == card.id))
    claim = db_session.get(Claim, link.claim_id)
    evidence = db_session.scalar(select(Evidence).where(Evidence.claim_id == claim.id))
    chunk = db_session.get(ContentChunk, evidence.content_chunk_id)
    assert claim.claim_type == "FACT"
    assert chunk.source_item_id if hasattr(chunk, "source_item_id") else chunk.extracted_document_id
    assert db_session.scalar(select(func.count()).select_from(Claim).where(Claim.text == claim.text)) == 1


def test_user_organization_view_hides_fake_analysis_artifacts(db_session, raw_root, tmp_path):
    from app.api.organization import organization

    created = _prepare(db_session, raw_root, tmp_path, "recorded fact sentence")
    org_run = _organize(db_session, created)
    analysis = db_session.get(AnalysisRun, org_run.analysis_run_id)
    created.source_item.system_scope = "USER"
    analysis.provider_type = "FAKE"
    analysis.model_name = "fake-model"
    db_session.flush()

    payload = organization(created.source_item.id, db_session, OrganizationService(db_session))

    assert payload["categories"] == []
    assert payload["topics"] == []
    assert payload["entities"] == []
    assert payload["knowledge_card_id"] is None
    assert payload["commercial_insight_id"] is None
    assert payload["project_candidate_id"] is None


def test_multi_category_business_and_knowledge(db_session, raw_root, tmp_path):
    created = _prepare(db_session, raw_root, tmp_path, "recorded fact sentence")
    chunk = _chunk(db_session, created.source_item.id)
    payload = _json(
        str(chunk.id),
        "recorded fact sentence",
        [{"name": "知识", "confidence": 0.9, "reason": "a"}, {"name": "商业", "confidence": 0.8, "reason": "b"}],
        entities=[{"name": "DeepSeek", "entity_type": "COMPANY", "evidence_chunk_ids": [str(chunk.id)]}],
    )
    _organize(db_session, created, payload)
    slugs = {
        db_session.get(Category, row.category_id).slug
        for row in db_session.scalars(select(SourceCategoryAssignment).where(SourceCategoryAssignment.source_item_id == created.source_item.id, SourceCategoryAssignment.status == "ACTIVE"))
    }
    assert {"knowledge", "business"} <= slugs
    insight = db_session.scalar(select(CommercialInsight).where(CommercialInsight.source_item_id == created.source_item.id))
    assert insight is not None
    assert db_session.scalar(select(CommercialInsightClaim).where(CommercialInsightClaim.commercial_insight_id == insight.id))
    assert "市场规模" not in insight.summary_snapshot


def test_other_fallback_and_user_override(db_session, raw_root, tmp_path):
    created = _prepare(db_session, raw_root, tmp_path, "recorded fact sentence")
    chunk = _chunk(db_session, created.source_item.id)
    payload = _json(str(chunk.id), "recorded fact sentence", [{"name": "知识", "confidence": 0.2, "reason": "low"}])
    run = _organize(db_session, created, payload)
    other = db_session.scalar(select(SourceCategoryAssignment).join(Category).where(SourceCategoryAssignment.organization_run_id == run.id, Category.slug == "other"))
    assert other.reason == "NO_CONFIDENT_CATEGORY"
    service = OrganizationService(db_session, threshold=0.7)
    service.set_categories(created.source_item.id, add=["business"], reject=["knowledge"], primary="business")
    second = _json(str(chunk.id), "recorded fact sentence", [{"name": "知识", "confidence": 0.99, "reason": "again"}, {"name": "商业", "confidence": 0.9, "reason": "biz"}])
    fake = FakeLLMProvider(script=[second])
    _service(db_session, _settings(), fake).start(created.source_item.id)
    rejected = db_session.scalar(
        select(SourceCategoryAssignment).join(Category).where(
            SourceCategoryAssignment.source_item_id == created.source_item.id,
            SourceCategoryAssignment.origin == "USER",
            Category.slug == "knowledge",
        )
    )
    assert rejected.status == "REJECTED"
    runs = list(db_session.scalars(select(OrganizationRun).where(OrganizationRun.source_item_id == created.source_item.id)))
    assert len(runs) == 2
    current = db_session.scalar(select(OrganizationRun).where(OrganizationRun.source_item_id == created.source_item.id, OrganizationRun.is_current.is_(True)))
    restored = db_session.scalar(
        select(SourceCategoryAssignment).where(
            SourceCategoryAssignment.organization_run_id == current.id,
            SourceCategoryAssignment.category_id == rejected.category_id,
            SourceCategoryAssignment.origin == "SYSTEM_ANALYSIS",
            SourceCategoryAssignment.status == "ACTIVE",
        )
    )
    assert restored is None


def test_topic_canonical_alias_and_no_fuzzy_merge(db_session, raw_root, tmp_path):
    created = _prepare(db_session, raw_root, tmp_path, "recorded fact sentence")
    chunk = _chunk(db_session, created.source_item.id)
    payload = _json(str(chunk.id), "recorded fact sentence", [{"name": "知识", "confidence": 0.9, "reason": "k"}], topics=["Agent", " agent ", "Agent Memory", "Memory"])
    _organize(db_session, created, payload)
    names = {row.normalized_name for row in db_session.scalars(select(Topic).where(Topic.merged_into_topic_id.is_(None)))}
    assert normalize_taxonomy_name("Agent") in names
    assert normalize_taxonomy_name("Agent Memory") in names
    assert normalize_taxonomy_name("Memory") in names
    assert len([name for name in names if name == normalize_taxonomy_name("Agent")]) == 1
    service = OrganizationService(db_session, threshold=0.7)
    agent = db_session.scalar(select(Topic).where(Topic.normalized_name == normalize_taxonomy_name("Agent")))
    memory = db_session.scalar(select(Topic).where(Topic.normalized_name == normalize_taxonomy_name("Memory")))
    service.add_alias("topic", agent.id, "AI Agent")
    again = _json(str(chunk.id), "recorded fact sentence", [{"name": "知识", "confidence": 0.9, "reason": "k"}], topics=["AI Agent"])
    _service(db_session, _settings(), FakeLLMProvider(script=[again])).start(created.source_item.id)
    assignments = list(db_session.scalars(select(SourceTopicAssignment).where(SourceTopicAssignment.topic_id == agent.id, SourceTopicAssignment.status == "ACTIVE")))
    assert assignments
    service.merge_topics(memory.id, agent.id)
    assert db_session.get(Topic, memory.id).merged_into_topic_id == agent.id
    assert db_session.scalar(select(func.count()).select_from(SourceTopicAssignment).where(SourceTopicAssignment.topic_id == memory.id)) == 0


def test_entity_exact_alias_merge_and_chunk_guard(db_session, raw_root, tmp_path):
    created = _prepare(db_session, raw_root, tmp_path, "recorded fact sentence")
    chunk = _chunk(db_session, created.source_item.id)
    payload = _json(
        str(chunk.id),
        "recorded fact sentence",
        [{"name": "知识", "confidence": 0.9, "reason": "k"}],
        entities=[
            {"name": "DeepSeek", "entity_type": "COMPANY", "evidence_chunk_ids": [str(chunk.id)]},
            {"name": " deepseek ", "entity_type": "COMPANY", "evidence_chunk_ids": [str(uuid.uuid4())]},
            {"name": "DeepSeek", "entity_type": "PRODUCT", "evidence_chunk_ids": []},
        ],
    )
    _organize(db_session, created, payload)
    source_entities = list(
        db_session.scalars(
            select(Entity)
            .join(EntityMention, EntityMention.entity_id == Entity.id)
            .where(EntityMention.source_item_id == created.source_item.id, Entity.merged_into_entity_id.is_(None))
            .distinct()
        )
    )
    companies = [item for item in source_entities if item.entity_type == "COMPANY"]
    products = [item for item in source_entities if item.entity_type == "PRODUCT"]
    assert len(companies) == 1
    assert len(products) == 1
    mention = db_session.scalar(select(EntityMention).where(EntityMention.source_item_id == created.source_item.id, EntityMention.entity_id == companies[0].id, EntityMention.content_chunk_id.is_not(None)))
    assert mention.content_chunk_id == chunk.id
    assert db_session.scalar(select(func.count()).select_from(EntityMention).where(EntityMention.content_chunk_id.is_(None), EntityMention.entity_id == companies[0].id)) == 0
    service = OrganizationService(db_session, threshold=0.7)
    other = Entity(id=uuid.uuid4(), name="深度求索", normalized_name=normalize_taxonomy_name("深度求索"), entity_type="COMPANY", description=None, merged_into_entity_id=None, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    db_session.add(other)
    db_session.commit()
    service.add_alias("entity", companies[0].id, "深度求索")
    service.merge_entities(other.id, companies[0].id)
    assert db_session.get(Entity, other.id).merged_into_entity_id == companies[0].id


def test_project_candidate_is_not_project_until_promote(db_session, raw_root, tmp_path):
    created = _prepare(db_session, raw_root, tmp_path, "recorded fact sentence")
    chunk = _chunk(db_session, created.source_item.id)
    payload = _json(str(chunk.id), "recorded fact sentence", [{"name": "发现项目", "confidence": 0.95, "reason": "idea"}])
    _organize(db_session, created, payload)
    candidate = db_session.scalar(select(ProjectCandidate).where(ProjectCandidate.source_item_id == created.source_item.id))
    assert candidate.status == "PROPOSED"
    assert db_session.scalar(select(func.count()).select_from(ProjectSource).where(ProjectSource.source_item_id == created.source_item.id)) == 0
    assert db_session.scalar(select(ProjectCandidateClaim).where(ProjectCandidateClaim.project_candidate_id == candidate.id))
    service = OrganizationService(db_session, threshold=0.7)
    project = service.promote_candidate(candidate.id)
    assert candidate.status == "PROMOTED"
    assert db_session.scalar(select(ProjectSource).where(ProjectSource.project_id == project.id, ProjectSource.source_item_id == created.source_item.id))


def test_reanalysis_can_replace_system_primary_category(db_session, raw_root, tmp_path):
    created = _prepare(db_session, raw_root, tmp_path, "recorded fact sentence")
    chunk = _chunk(db_session, created.source_item.id)
    quote = chunk.content.splitlines()[0][:180]
    first = _json(str(chunk.id), quote, [{"name": "其他", "confidence": 0.9, "reason": "old"}])
    second = _json(str(chunk.id), quote, [{"name": "知识", "confidence": 0.9, "reason": "new"}])
    _service(db_session, _settings(), FakeLLMProvider(script=[first])).start(created.source_item.id)
    _service(db_session, _settings(), FakeLLMProvider(script=[second])).start(created.source_item.id)
    current_analysis = db_session.scalar(select(AnalysisRun).where(AnalysisRun.source_item_id == created.source_item.id, AnalysisRun.is_current.is_(True)))
    current_org = db_session.scalar(select(OrganizationRun).where(OrganizationRun.source_item_id == created.source_item.id, OrganizationRun.is_current.is_(True)))
    assert current_org.analysis_run_id == current_analysis.id
    primaries = list(
        db_session.scalars(
            select(SourceCategoryAssignment).where(
                SourceCategoryAssignment.source_item_id == created.source_item.id,
                SourceCategoryAssignment.status == "ACTIVE",
                SourceCategoryAssignment.is_primary.is_(True),
            )
        )
    )
    assert len(primaries) == 1
    assert db_session.get(Category, primaries[0].category_id).slug == "knowledge"
    assert db_session.scalar(select(func.count()).select_from(OrganizationRun).where(OrganizationRun.source_item_id == created.source_item.id)) == 2


def test_idempotent_organize_and_tags(db_session, raw_root, tmp_path):
    created = _prepare(db_session, raw_root, tmp_path, "recorded fact sentence")
    first = _organize(db_session, created)
    second = OrganizationService(db_session, threshold=0.7).organize(created.source_item.id)
    assert first.id == second.id
    assert db_session.scalar(select(func.count()).select_from(KnowledgeCard).where(KnowledgeCard.source_item_id == created.source_item.id)) == 1
    OrganizationService(db_session, threshold=0.7).set_tags(created.source_item.id, add=["重点"], remove=[])
    OrganizationService(db_session, threshold=0.7).set_tags(created.source_item.id, add=[], remove=["重点"])
    from app.models.organization import SourceTag

    assert db_session.scalar(select(func.count()).select_from(SourceTag).where(SourceTag.source_item_id == created.source_item.id)) == 0


def test_discovered_source_and_collection_date(db_session, raw_root, tmp_path):
    created = _prepare(db_session, raw_root, tmp_path, "recorded fact sentence")
    _organize(db_session, created)
    source = db_session.get(SourceItem, created.source_item.id)
    user_rows = list(db_session.scalars(select(IngestionRecord).where(IngestionRecord.source_item_id == source.id, IngestionRecord.origin == "USER_COLLECTION")))
    assert user_rows
    discovered = SourceItem(id=uuid.uuid4(), source_type="URL", original_url="https://example.com/x", canonical_url="https://example.com/x", display_name="discovered", content_hash=None, status="STORED", privacy_level="PRIVATE", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    db_session.add(discovered)
    db_session.add(IngestionRecord(id=uuid.uuid4(), source_item_id=discovered.id, ingestion_type="URL", origin="SYSTEM_DISCOVERY", original_input="https://example.com/x", collected_at=datetime.now(timezone.utc), duplicate_detected=False, duplicate_reason=None, status="STORED", created_at=datetime.now(timezone.utc)))
    db_session.commit()
    from app.api.organization import library

    mine = library(scope="mine", session=db_session)
    ids = {item["source_id"] for item in mine["items"]}
    assert source.id in ids
    assert discovered.id not in ids
    assert all(item["collection_origin"] == "USER_COLLECTION" for item in mine["items"] if item["source_id"] == source.id)
    early = library(scope="mine", collected_to=datetime(2000, 1, 1, tzinfo=timezone.utc), session=db_session)
    assert source.id not in {item["source_id"] for item in early["items"]}
