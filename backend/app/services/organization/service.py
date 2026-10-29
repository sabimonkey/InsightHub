import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.analysis import AnalysisResult, AnalysisRun, Claim
from app.models.extraction import ContentChunk, ExtractedDocument
from app.models.organization import (
    Category,
    CommercialInsight,
    CommercialInsightClaim,
    CommercialInsightEntity,
    Entity,
    EntityAlias,
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
    TopicAlias,
)
from app.models.source_item import SourceItem
from app.services.organization.normalize import (
    CLAIM_ROLES,
    DEFAULT_CATEGORIES,
    ENTITY_TYPES,
    acceptable_taxonomy_name,
    category_slug,
    normalize_taxonomy_name,
)


class OrganizationError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class OrganizationService:
    def __init__(self, session: Session, *, threshold: float = 0.7) -> None:
        self.session = session
        self.threshold = threshold

    def organize(self, source_id: uuid.UUID) -> OrganizationRun:
        self.ensure_default_categories()
        source = self.session.get(SourceItem, source_id)
        if source is None:
            raise OrganizationError(404, "SOURCE_NOT_FOUND", "找不到该资料。")
        analysis = self.session.scalar(
            select(AnalysisRun).where(AnalysisRun.source_item_id == source_id, AnalysisRun.is_current.is_(True), AnalysisRun.status.in_(("SUCCEEDED", "PARTIAL")))
        )
        if analysis is None:
            raise OrganizationError(409, "ANALYSIS_REQUIRED", "资料还没有可组织的分析结果。")
        existing = self.session.scalar(
            select(OrganizationRun).where(OrganizationRun.analysis_run_id == analysis.id, OrganizationRun.status.in_(("SUCCEEDED", "PARTIAL")))
        )
        if existing is not None:
            return existing
        result = self.session.scalar(select(AnalysisResult).where(AnalysisResult.analysis_run_id == analysis.id))
        if result is None:
            raise OrganizationError(409, "ANALYSIS_REQUIRED", "分析结果缺少结构化内容。")
        now = datetime.now(timezone.utc)
        run = OrganizationRun(
            id=uuid.uuid4(),
            source_item_id=source.id,
            analysis_run_id=analysis.id,
            status="RUNNING",
            is_current=False,
            started_at=now,
            created_at=now,
        )
        self.session.add(run)
        self.session.flush()
        payload = result.raw_structured_json or {}
        self._assign_categories(source, run, analysis, payload)
        self._assign_topics(source, run, analysis, payload.get("topic_candidates") or [])
        entities = list({item.id: item for item in self._assign_entities(source, analysis, payload.get("entities") or [])}.values())
        active_slugs = self._active_slugs(source.id, run.id)
        title = self._title(source, analysis)
        if "knowledge" in active_slugs:
            self._card(KnowledgeCard, KnowledgeCardClaim, "knowledge_card_id", source, result, run, title)
        if "business" in active_slugs:
            insight = self._card(CommercialInsight, CommercialInsightClaim, "commercial_insight_id", source, result, run, title)
            for entity in entities:
                self.session.add(CommercialInsightEntity(id=uuid.uuid4(), commercial_insight_id=insight.id, entity_id=entity.id))
        if "project_discovery" in active_slugs:
            self._card(ProjectCandidate, ProjectCandidateClaim, "project_candidate_id", source, result, run, title, extra={"status": "PROPOSED"})
        self._mark_current(run)
        run.status = "SUCCEEDED"
        run.completed_at = datetime.now(timezone.utc)
        self.session.commit()
        return run

    def ensure_default_categories(self) -> None:
        now = datetime.now(timezone.utc)
        for slug, name, order in DEFAULT_CATEGORIES:
            row = self.session.scalar(select(Category).where(Category.slug == slug))
            if row is None:
                self.session.add(
                    Category(
                        id=uuid.uuid4(),
                        name=name,
                        slug=slug,
                        description=None,
                        display_order=order,
                        is_system_default=True,
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    )
                )
        self.session.flush()

    def create_category(self, name: str, description: str | None, display_order: int) -> Category:
        slug = normalize_taxonomy_name(name).replace(" ", "_")
        if not acceptable_taxonomy_name(name) or slug in {item[0] for item in DEFAULT_CATEGORIES}:
            raise OrganizationError(400, "INVALID_CATEGORY", "类别名称不可用。")
        if self.session.scalar(select(Category).where(Category.slug == slug)):
            raise OrganizationError(409, "CATEGORY_EXISTS", "类别已存在。")
        now = datetime.now(timezone.utc)
        row = Category(
            id=uuid.uuid4(),
            name=name.strip(),
            slug=slug,
            description=description,
            display_order=display_order,
            is_system_default=False,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        self.session.commit()
        return row

    def update_category(self, category_id: uuid.UUID, *, name: str | None, description: str | None, display_order: int | None, is_active: bool | None) -> Category:
        row = self.session.get(Category, category_id)
        if row is None:
            raise OrganizationError(404, "CATEGORY_NOT_FOUND", "找不到类别。")
        if is_active is False and row.is_system_default:
            raise OrganizationError(409, "SYSTEM_CATEGORY_PROTECTED", "默认类别不能停用或删除。")
        if name:
            row.name = name.strip()
        if description is not None:
            row.description = description
        if display_order is not None:
            row.display_order = display_order
        if is_active is not None and not row.is_system_default:
            row.is_active = is_active
        row.updated_at = datetime.now(timezone.utc)
        self.session.commit()
        return row

    def set_categories(self, source_id: uuid.UUID, *, add: list[str], reject: list[str], primary: str | None) -> None:
        self.ensure_default_categories()
        source = self._source(source_id)
        analysis = self._current_analysis(source.id)
        for slug in reject:
            category = self._category(slug)
            self._user_category(source.id, category.id, "REJECTED", analysis.id if analysis else None, primary=False)
        for slug in add:
            category = self._category(slug)
            self._user_category(source.id, category.id, "ACTIVE", analysis.id if analysis else None, primary=False)
        if primary:
            self._set_primary(source.id, self._category(primary).id)
        if analysis is not None:
            run = self.session.scalar(select(OrganizationRun).where(OrganizationRun.analysis_run_id == analysis.id, OrganizationRun.status == "SUCCEEDED"))
            if run is not None:
                self._ensure_artifacts_for_user_categories(source, analysis, run)
        self.session.commit()

    def set_topics(self, source_id: uuid.UUID, *, add: list[str], reject_ids: list[uuid.UUID]) -> None:
        source = self._source(source_id)
        analysis = self._current_analysis(source.id)
        for topic_id in reject_ids:
            topic = self._canonical_topic(self.session.get(Topic, topic_id))
            if topic is None:
                raise OrganizationError(404, "TOPIC_NOT_FOUND", "找不到主题。")
            self._user_topic(source.id, topic.id, "REJECTED", analysis.id if analysis else None)
        for name in add:
            topic = self._find_or_create_topic(name, allow_create=True)
            if topic is None:
                raise OrganizationError(400, "INVALID_TOPIC", "主题名称不可用。")
            self._user_topic(source.id, topic.id, "ACTIVE", analysis.id if analysis else None)
        self.session.commit()

    def set_topic_parent(self, topic_id: uuid.UUID, parent_id: uuid.UUID | None) -> Topic:
        topic = self._canonical_topic(self.session.get(Topic, topic_id))
        if topic is None:
            raise OrganizationError(404, "TOPIC_NOT_FOUND", "找不到主题。")
        if parent_id is not None:
            parent = self._canonical_topic(self.session.get(Topic, parent_id))
            if parent is None or parent.id == topic.id:
                raise OrganizationError(400, "INVALID_TOPIC_PARENT", "父主题不可用。")
            topic.parent_id = parent.id
        else:
            topic.parent_id = None
        topic.updated_at = datetime.now(timezone.utc)
        self.session.commit()
        return topic

    def merge_topics(self, source_id: uuid.UUID, canonical_id: uuid.UUID) -> Topic:
        source = self.session.get(Topic, source_id)
        canonical = self._canonical_topic(self.session.get(Topic, canonical_id))
        if source is None or canonical is None or source.id == canonical.id:
            raise OrganizationError(400, "INVALID_TOPIC_MERGE", "无法合并这些主题。")
        source.merged_into_topic_id = canonical.id
        source.updated_at = datetime.now(timezone.utc)
        for alias in self.session.scalars(select(TopicAlias).where(TopicAlias.topic_id == source.id)):
            alias.topic_id = canonical.id
        normalized = source.normalized_name
        if not self.session.scalar(select(TopicAlias).where(TopicAlias.normalized_alias == normalized)):
            self.session.add(TopicAlias(id=uuid.uuid4(), topic_id=canonical.id, alias=source.name, normalized_alias=normalized, created_at=datetime.now(timezone.utc)))
        for assignment in list(self.session.scalars(select(SourceTopicAssignment).where(SourceTopicAssignment.topic_id == source.id))):
            clash = self.session.scalar(
                select(SourceTopicAssignment).where(
                    SourceTopicAssignment.source_item_id == assignment.source_item_id,
                    SourceTopicAssignment.topic_id == canonical.id,
                    SourceTopicAssignment.origin == assignment.origin,
                    SourceTopicAssignment.organization_run_id == assignment.organization_run_id,
                )
            )
            if clash is None:
                assignment.topic_id = canonical.id
            else:
                self.session.delete(assignment)
        self.session.commit()
        return canonical

    def merge_entities(self, source_id: uuid.UUID, canonical_id: uuid.UUID) -> Entity:
        source = self.session.get(Entity, source_id)
        canonical = self._canonical_entity(self.session.get(Entity, canonical_id))
        if source is None or canonical is None or source.id == canonical.id or source.entity_type != canonical.entity_type:
            raise OrganizationError(400, "INVALID_ENTITY_MERGE", "无法合并这些实体。")
        source.merged_into_entity_id = canonical.id
        source.updated_at = datetime.now(timezone.utc)
        for alias in self.session.scalars(select(EntityAlias).where(EntityAlias.entity_id == source.id)):
            alias.entity_id = canonical.id
        if not self.session.scalar(select(EntityAlias).where(EntityAlias.normalized_alias == source.normalized_name, EntityAlias.entity_type == source.entity_type)):
            self.session.add(
                EntityAlias(
                    id=uuid.uuid4(),
                    entity_id=canonical.id,
                    alias=source.name,
                    normalized_alias=source.normalized_name,
                    entity_type=source.entity_type,
                    created_at=datetime.now(timezone.utc),
                )
            )
        for mention in self.session.scalars(select(EntityMention).where(EntityMention.entity_id == source.id)):
            mention.entity_id = canonical.id
        for link in self.session.scalars(select(CommercialInsightEntity).where(CommercialInsightEntity.entity_id == source.id)):
            link.entity_id = canonical.id
        self.session.commit()
        return canonical

    def add_alias(self, kind: str, target_id: uuid.UUID, alias: str) -> None:
        if not acceptable_taxonomy_name(alias):
            raise OrganizationError(400, "INVALID_ALIAS", "别名不可用。")
        normalized = normalize_taxonomy_name(alias)
        now = datetime.now(timezone.utc)
        if kind == "topic":
            topic = self._canonical_topic(self.session.get(Topic, target_id))
            if topic is None:
                raise OrganizationError(404, "TOPIC_NOT_FOUND", "找不到主题。")
            if not self.session.scalar(select(TopicAlias).where(TopicAlias.normalized_alias == normalized)):
                self.session.add(TopicAlias(id=uuid.uuid4(), topic_id=topic.id, alias=alias.strip(), normalized_alias=normalized, created_at=now))
        else:
            entity = self._canonical_entity(self.session.get(Entity, target_id))
            if entity is None:
                raise OrganizationError(404, "ENTITY_NOT_FOUND", "找不到实体。")
            if not self.session.scalar(select(EntityAlias).where(EntityAlias.normalized_alias == normalized, EntityAlias.entity_type == entity.entity_type)):
                self.session.add(EntityAlias(id=uuid.uuid4(), entity_id=entity.id, alias=alias.strip(), normalized_alias=normalized, entity_type=entity.entity_type, created_at=now))
        self.session.commit()

    def set_tags(self, source_id: uuid.UUID, *, add: list[str], remove: list[str]) -> None:
        source = self._source(source_id)
        for name in remove:
            tag = self._tag(name, create=False)
            if tag is not None:
                row = self.session.scalar(select(SourceTag).where(SourceTag.source_item_id == source.id, SourceTag.tag_id == tag.id))
                if row is not None:
                    self.session.delete(row)
        for name in add:
            tag = self._tag(name, create=True)
            if tag is None:
                raise OrganizationError(400, "INVALID_TAG", "标签不可用。")
            if self.session.scalar(select(SourceTag).where(SourceTag.source_item_id == source.id, SourceTag.tag_id == tag.id)) is None:
                self.session.add(SourceTag(id=uuid.uuid4(), source_item_id=source.id, tag_id=tag.id, created_at=datetime.now(timezone.utc)))
        self.session.commit()

    def reject_candidate(self, candidate_id: uuid.UUID) -> ProjectCandidate:
        row = self.session.get(ProjectCandidate, candidate_id)
        if row is None:
            raise OrganizationError(404, "CANDIDATE_NOT_FOUND", "找不到项目候选。")
        row.status = "REJECTED"
        row.updated_at = datetime.now(timezone.utc)
        self.session.commit()
        return row

    def promote_candidate(self, candidate_id: uuid.UUID) -> Project:
        row = self.session.get(ProjectCandidate, candidate_id)
        if row is None:
            raise OrganizationError(404, "CANDIDATE_NOT_FOUND", "找不到项目候选。")
        if row.status == "REJECTED":
            raise OrganizationError(409, "CANDIDATE_REJECTED", "已拒绝的候选不能升级为项目。")
        existing = self.session.scalar(select(Project).where(Project.origin_project_candidate_id == row.id))
        if existing is not None:
            return existing
        now = datetime.now(timezone.utc)
        project = Project(
            id=uuid.uuid4(),
            name=row.title,
            description=row.summary_snapshot,
            status="NEW",
            origin_project_candidate_id=row.id,
            created_at=now,
            updated_at=now,
        )
        self.session.add(project)
        self.session.flush()
        self.session.add(ProjectSource(id=uuid.uuid4(), project_id=project.id, source_item_id=row.source_item_id, created_at=now))
        row.status = "PROMOTED"
        row.updated_at = now
        self.session.commit()
        return project

    def _assign_categories(self, source: SourceItem, run: OrganizationRun, analysis: AnalysisRun, payload: dict) -> None:
        rejected = {
            row.category_id
            for row in self.session.scalars(
                select(SourceCategoryAssignment).where(
                    SourceCategoryAssignment.source_item_id == source.id,
                    SourceCategoryAssignment.origin == "USER",
                    SourceCategoryAssignment.status == "REJECTED",
                )
            )
        }
        chosen: list[tuple[Category, float, str | None]] = []
        for item in payload.get("category_candidates") or []:
            slug = category_slug(str(item.get("name") or ""))
            confidence = float(item.get("confidence") or 0)
            if slug is None or confidence < self.threshold:
                continue
            category = self.session.scalar(select(Category).where(Category.slug == slug, Category.is_active.is_(True)))
            if category is None or category.id in rejected:
                continue
            chosen.append((category, confidence, item.get("reason")))
        if not chosen:
            other = self.session.scalar(select(Category).where(Category.slug == "other"))
            if other is not None and other.id not in rejected:
                chosen.append((other, 0, "NO_CONFIDENT_CATEGORY"))
        user_primary = self.session.scalar(
            select(SourceCategoryAssignment).where(
                SourceCategoryAssignment.source_item_id == source.id,
                SourceCategoryAssignment.origin == "USER",
                SourceCategoryAssignment.status == "ACTIVE",
                SourceCategoryAssignment.is_primary.is_(True),
            )
        )
        best = max(chosen, key=lambda item: item[1]) if chosen else None
        now = datetime.now(timezone.utc)
        if user_primary is None and best is not None:
            self.session.execute(
                update(SourceCategoryAssignment)
                .where(
                    SourceCategoryAssignment.source_item_id == source.id,
                    SourceCategoryAssignment.origin == "SYSTEM_ANALYSIS",
                    SourceCategoryAssignment.status == "ACTIVE",
                    SourceCategoryAssignment.is_primary.is_(True),
                )
                .values(is_primary=False, updated_at=now)
            )
            self.session.flush()
        for category, confidence, reason in chosen:
            self.session.add(
                SourceCategoryAssignment(
                    id=uuid.uuid4(),
                    source_item_id=source.id,
                    category_id=category.id,
                    organization_run_id=run.id,
                    analysis_run_id=analysis.id,
                    origin="SYSTEM_ANALYSIS",
                    confidence=confidence,
                    reason=reason,
                    status="ACTIVE",
                    is_primary=user_primary is None and best is not None and category.id == best[0].id,
                    created_at=now,
                    updated_at=now,
                )
            )
        self.session.flush()

    def _assign_topics(self, source: SourceItem, run: OrganizationRun, analysis: AnalysisRun, names: list) -> list[Topic]:
        rejected = {
            row.topic_id
            for row in self.session.scalars(
                select(SourceTopicAssignment).where(
                    SourceTopicAssignment.source_item_id == source.id,
                    SourceTopicAssignment.origin == "USER",
                    SourceTopicAssignment.status == "REJECTED",
                )
            )
        }
        created: list[Topic] = []
        seen: set[uuid.UUID] = set()
        now = datetime.now(timezone.utc)
        for name in names:
            topic = self._find_or_create_topic(str(name), allow_create=True)
            if topic is None or topic.id in rejected or topic.id in seen:
                continue
            seen.add(topic.id)
            self.session.add(
                SourceTopicAssignment(
                    id=uuid.uuid4(),
                    source_item_id=source.id,
                    topic_id=topic.id,
                    organization_run_id=run.id,
                    analysis_run_id=analysis.id,
                    origin="SYSTEM_ANALYSIS",
                    confidence=None,
                    status="ACTIVE",
                    created_at=now,
                )
            )
            created.append(topic)
        self.session.flush()
        return created

    def _assign_entities(self, source: SourceItem, analysis: AnalysisRun, items: list) -> list[Entity]:
        document_id = analysis.extracted_document_id
        found: list[Entity] = []
        now = datetime.now(timezone.utc)
        for item in items:
            name = str(item.get("name") or "")
            entity_type = str(item.get("entity_type") or "OTHER").upper()
            if entity_type not in ENTITY_TYPES or not acceptable_taxonomy_name(name):
                continue
            entity = self._find_or_create_entity(name, entity_type)
            found.append(entity)
            chunk_ids = item.get("evidence_chunk_ids") or [None]
            for chunk_id in chunk_ids:
                parsed = self._owned_chunk(chunk_id, document_id)
                if chunk_id and parsed is None:
                    continue
                self.session.add(
                    EntityMention(
                        id=uuid.uuid4(),
                        entity_id=entity.id,
                        source_item_id=source.id,
                        analysis_run_id=analysis.id,
                        mention_text=name.strip()[:256],
                        content_chunk_id=parsed,
                        confidence=None,
                        created_at=now,
                    )
                )
        self.session.flush()
        return found

    def _card(self, model, link_model, link_field: str, source: SourceItem, result: AnalysisResult, run: OrganizationRun, title: str, extra: dict | None = None):
        now = datetime.now(timezone.utc)
        values = {
            "id": uuid.uuid4(),
            "source_item_id": source.id,
            "analysis_result_id": result.id,
            "organization_run_id": run.id,
            "title": title,
            "summary_snapshot": result.summary,
            "created_at": now,
        }
        if model is not ProjectCandidate:
            values["is_current"] = True
        if model is KnowledgeCard:
            values["updated_at"] = now
            values["status"] = "ACTIVE"
        values.update(extra or {})
        if model is KnowledgeCard:
            self.session.execute(update(KnowledgeCard).where(KnowledgeCard.source_item_id == source.id).values(is_current=False))
        if model is CommercialInsight:
            self.session.execute(update(CommercialInsight).where(CommercialInsight.source_item_id == source.id).values(is_current=False))
        row = model(**values)
        self.session.add(row)
        self.session.flush()
        claims = list(self.session.scalars(select(Claim).where(Claim.analysis_result_id == result.id)).all())
        ordered = sorted(claims, key=lambda claim: (-(claim.importance or 0), claim.sequence))
        for index, claim in enumerate(ordered):
            role = CLAIM_ROLES.get(claim.claim_type)
            if role is None:
                continue
            self.session.add(link_model(id=uuid.uuid4(), **{link_field: row.id, "claim_id": claim.id, "role": role, "display_order": index}))
        return row

    def _ensure_artifacts_for_user_categories(self, source: SourceItem, analysis: AnalysisRun, run: OrganizationRun) -> None:
        result = self.session.scalar(select(AnalysisResult).where(AnalysisResult.analysis_run_id == analysis.id))
        if result is None:
            return
        slugs = self._active_slugs(source.id, run.id)
        title = self._title(source, analysis)
        if "knowledge" in slugs and self.session.scalar(select(KnowledgeCard).where(KnowledgeCard.organization_run_id == run.id)) is None:
            self._card(KnowledgeCard, KnowledgeCardClaim, "knowledge_card_id", source, result, run, title)
        if "business" in slugs and self.session.scalar(select(CommercialInsight).where(CommercialInsight.organization_run_id == run.id)) is None:
            insight = self._card(CommercialInsight, CommercialInsightClaim, "commercial_insight_id", source, result, run, title)
            for entity_id in self.session.scalars(select(EntityMention.entity_id).where(EntityMention.source_item_id == source.id, EntityMention.analysis_run_id == analysis.id)):
                if self.session.scalar(select(CommercialInsightEntity).where(CommercialInsightEntity.commercial_insight_id == insight.id, CommercialInsightEntity.entity_id == entity_id)) is None:
                    self.session.add(CommercialInsightEntity(id=uuid.uuid4(), commercial_insight_id=insight.id, entity_id=entity_id))
        if "project_discovery" in slugs and self.session.scalar(select(ProjectCandidate).where(ProjectCandidate.organization_run_id == run.id)) is None:
            self._card(ProjectCandidate, ProjectCandidateClaim, "project_candidate_id", source, result, run, title, extra={"status": "PROPOSED", "updated_at": datetime.now(timezone.utc)})

    def _active_slugs(self, source_id: uuid.UUID, run_id: uuid.UUID) -> set[str]:
        rejected = {
            row.category_id
            for row in self.session.scalars(
                select(SourceCategoryAssignment).where(
                    SourceCategoryAssignment.source_item_id == source_id,
                    SourceCategoryAssignment.origin == "USER",
                    SourceCategoryAssignment.status == "REJECTED",
                )
            )
        }
        slugs: set[str] = set()
        rows = list(
            self.session.scalars(
                select(SourceCategoryAssignment).where(
                    SourceCategoryAssignment.source_item_id == source_id,
                    SourceCategoryAssignment.status == "ACTIVE",
                )
            )
        )
        for row in rows:
            if row.category_id in rejected:
                continue
            if row.origin == "SYSTEM_ANALYSIS" and row.organization_run_id != run_id:
                continue
            category = self.session.get(Category, row.category_id)
            if category is not None:
                slugs.add(category.slug)
        return slugs

    def _find_or_create_topic(self, name: str, *, allow_create: bool) -> Topic | None:
        if not acceptable_taxonomy_name(name):
            return None
        normalized = normalize_taxonomy_name(name)
        topic = self.session.scalar(select(Topic).where(Topic.normalized_name == normalized, Topic.merged_into_topic_id.is_(None)))
        if topic is not None:
            return topic
        alias = self.session.scalar(select(TopicAlias).where(TopicAlias.normalized_alias == normalized))
        if alias is not None:
            return self._canonical_topic(self.session.get(Topic, alias.topic_id))
        if not allow_create:
            return None
        now = datetime.now(timezone.utc)
        topic = Topic(id=uuid.uuid4(), name=name.strip(), normalized_name=normalized, description=None, parent_id=None, merged_into_topic_id=None, created_at=now, updated_at=now)
        self.session.add(topic)
        self.session.flush()
        return topic

    def _find_or_create_entity(self, name: str, entity_type: str) -> Entity:
        normalized = normalize_taxonomy_name(name)
        entity = self.session.scalar(select(Entity).where(Entity.normalized_name == normalized, Entity.entity_type == entity_type, Entity.merged_into_entity_id.is_(None)))
        if entity is not None:
            return entity
        alias = self.session.scalar(select(EntityAlias).where(EntityAlias.normalized_alias == normalized, EntityAlias.entity_type == entity_type))
        if alias is not None:
            found = self._canonical_entity(self.session.get(Entity, alias.entity_id))
            if found is not None:
                return found
        now = datetime.now(timezone.utc)
        entity = Entity(id=uuid.uuid4(), name=name.strip(), normalized_name=normalized, entity_type=entity_type, description=None, merged_into_entity_id=None, created_at=now, updated_at=now)
        self.session.add(entity)
        self.session.flush()
        return entity

    def _canonical_topic(self, topic: Topic | None) -> Topic | None:
        seen: set[uuid.UUID] = set()
        while topic is not None and topic.merged_into_topic_id and topic.id not in seen:
            seen.add(topic.id)
            topic = self.session.get(Topic, topic.merged_into_topic_id)
        return topic

    def _canonical_entity(self, entity: Entity | None) -> Entity | None:
        seen: set[uuid.UUID] = set()
        while entity is not None and entity.merged_into_entity_id and entity.id not in seen:
            seen.add(entity.id)
            entity = self.session.get(Entity, entity.merged_into_entity_id)
        return entity

    def _user_category(self, source_id: uuid.UUID, category_id: uuid.UUID, status: str, analysis_id: uuid.UUID | None, *, primary: bool) -> None:
        row = self.session.scalar(
            select(SourceCategoryAssignment).where(
                SourceCategoryAssignment.source_item_id == source_id,
                SourceCategoryAssignment.category_id == category_id,
                SourceCategoryAssignment.origin == "USER",
            )
        )
        now = datetime.now(timezone.utc)
        if row is None:
            self.session.add(
                SourceCategoryAssignment(
                    id=uuid.uuid4(),
                    source_item_id=source_id,
                    category_id=category_id,
                    organization_run_id=None,
                    analysis_run_id=analysis_id,
                    origin="USER",
                    confidence=None,
                    reason=None,
                    status=status,
                    is_primary=False,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            row.status = status
            row.updated_at = now
            if status != "ACTIVE":
                row.is_primary = False
        self.session.flush()

    def _user_topic(self, source_id: uuid.UUID, topic_id: uuid.UUID, status: str, analysis_id: uuid.UUID | None) -> None:
        row = self.session.scalar(
            select(SourceTopicAssignment).where(
                SourceTopicAssignment.source_item_id == source_id,
                SourceTopicAssignment.topic_id == topic_id,
                SourceTopicAssignment.origin == "USER",
            )
        )
        now = datetime.now(timezone.utc)
        if row is None:
            self.session.add(
                SourceTopicAssignment(
                    id=uuid.uuid4(),
                    source_item_id=source_id,
                    topic_id=topic_id,
                    organization_run_id=None,
                    analysis_run_id=analysis_id,
                    origin="USER",
                    confidence=None,
                    status=status,
                    created_at=now,
                )
            )
        else:
            row.status = status
        self.session.flush()

    def _set_primary(self, source_id: uuid.UUID, category_id: uuid.UUID) -> None:
        self.session.execute(
            update(SourceCategoryAssignment)
            .where(SourceCategoryAssignment.source_item_id == source_id, SourceCategoryAssignment.is_primary.is_(True))
            .values(is_primary=False)
        )
        row = self.session.scalar(
            select(SourceCategoryAssignment).where(
                SourceCategoryAssignment.source_item_id == source_id,
                SourceCategoryAssignment.category_id == category_id,
                SourceCategoryAssignment.origin == "USER",
                SourceCategoryAssignment.status == "ACTIVE",
            )
        )
        if row is None:
            self._user_category(source_id, category_id, "ACTIVE", None, primary=False)
            row = self.session.scalar(
                select(SourceCategoryAssignment).where(
                    SourceCategoryAssignment.source_item_id == source_id,
                    SourceCategoryAssignment.category_id == category_id,
                    SourceCategoryAssignment.origin == "USER",
                )
            )
        if row is not None:
            row.is_primary = True
            row.status = "ACTIVE"
        self.session.flush()

    def _owned_chunk(self, chunk_id, document_id: uuid.UUID) -> uuid.UUID | None:
        if not chunk_id:
            return None
        try:
            parsed = uuid.UUID(str(chunk_id))
        except ValueError:
            return None
        chunk = self.session.get(ContentChunk, parsed)
        if chunk is None or chunk.extracted_document_id != document_id:
            return None
        return chunk.id

    def _title(self, source: SourceItem, analysis: AnalysisRun) -> str:
        document = self.session.get(ExtractedDocument, analysis.extracted_document_id)
        if document is not None and document.title and document.title.strip():
            return document.title.strip()[:256]
        if source.display_name and source.display_name.strip():
            return source.display_name.strip()[:256]
        return "Untitled Source"

    def _mark_current(self, run: OrganizationRun) -> None:
        self.session.execute(update(OrganizationRun).where(OrganizationRun.source_item_id == run.source_item_id, OrganizationRun.id != run.id).values(is_current=False))
        run.is_current = True

    def _source(self, source_id: uuid.UUID) -> SourceItem:
        source = self.session.get(SourceItem, source_id)
        if source is None:
            raise OrganizationError(404, "SOURCE_NOT_FOUND", "找不到该资料。")
        return source

    def _current_analysis(self, source_id: uuid.UUID) -> AnalysisRun | None:
        return self.session.scalar(select(AnalysisRun).where(AnalysisRun.source_item_id == source_id, AnalysisRun.is_current.is_(True)))

    def _category(self, slug_or_name: str) -> Category:
        slug = category_slug(slug_or_name) or normalize_taxonomy_name(slug_or_name).replace(" ", "_")
        row = self.session.scalar(select(Category).where(Category.slug == slug, Category.is_active.is_(True)))
        if row is None:
            raise OrganizationError(404, "CATEGORY_NOT_FOUND", "找不到类别。")
        return row

    def _tag(self, name: str, *, create: bool) -> Tag | None:
        if not acceptable_taxonomy_name(name, limit=64):
            return None
        normalized = normalize_taxonomy_name(name)
        row = self.session.scalar(select(Tag).where(Tag.normalized_name == normalized))
        if row is not None or not create:
            return row
        row = Tag(id=uuid.uuid4(), name=name.strip(), normalized_name=normalized, created_at=datetime.now(timezone.utc))
        self.session.add(row)
        self.session.flush()
        return row
