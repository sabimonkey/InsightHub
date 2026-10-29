import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OrganizationRun(Base):
    __tablename__ = "organization_runs"
    __table_args__ = (
        Index("ix_organization_runs_source_item_id", "source_item_id"),
        Index("uq_organization_runs_current", "source_item_id", unique=True, postgresql_where=text("is_current")),
        Index(
            "uq_organization_runs_analysis_success",
            "analysis_run_id",
            unique=True,
            postgresql_where=text("status IN ('SUCCEEDED', 'PARTIAL')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False)
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (Index("uq_categories_slug", "slug", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_system_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SourceCategoryAssignment(Base):
    __tablename__ = "source_category_assignments"
    __table_args__ = (
        Index("uq_source_category_primary", "source_item_id", unique=True, postgresql_where=text("is_primary AND status = 'ACTIVE'")),
        Index(
            "uq_source_category_system_run",
            "source_item_id",
            "category_id",
            "organization_run_id",
            unique=True,
            postgresql_where=text("origin = 'SYSTEM_ANALYSIS' AND organization_run_id IS NOT NULL"),
        ),
        Index(
            "uq_source_category_user",
            "source_item_id",
            "category_id",
            unique=True,
            postgresql_where=text("origin = 'USER'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False)
    organization_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organization_runs.id", ondelete="RESTRICT"), nullable=True)
    analysis_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="RESTRICT"), nullable=True)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (Index("uq_topics_normalized_open", "normalized_name", unique=True, postgresql_where=text("merged_into_topic_id IS NULL")),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("topics.id", ondelete="RESTRICT"), nullable=True)
    merged_into_topic_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("topics.id", ondelete="RESTRICT"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TopicAlias(Base):
    __tablename__ = "topic_aliases"
    __table_args__ = (Index("uq_topic_aliases_normalized", "normalized_alias", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("topics.id", ondelete="RESTRICT"), nullable=False)
    alias: Mapped[str] = mapped_column(String(128), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SourceTopicAssignment(Base):
    __tablename__ = "source_topic_assignments"
    __table_args__ = (
        Index(
            "uq_source_topic_system_run",
            "source_item_id",
            "topic_id",
            "organization_run_id",
            unique=True,
            postgresql_where=text("origin = 'SYSTEM_ANALYSIS' AND organization_run_id IS NOT NULL"),
        ),
        Index("uq_source_topic_user", "source_item_id", "topic_id", unique=True, postgresql_where=text("origin = 'USER'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False)
    topic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("topics.id", ondelete="RESTRICT"), nullable=False)
    organization_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organization_runs.id", ondelete="RESTRICT"), nullable=True)
    analysis_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="RESTRICT"), nullable=True)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Entity(Base):
    __tablename__ = "entities"
    __table_args__ = (
        Index(
            "uq_entities_name_type_open",
            "normalized_name",
            "entity_type",
            unique=True,
            postgresql_where=text("merged_into_entity_id IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    merged_into_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("entities.id", ondelete="RESTRICT"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EntityAlias(Base):
    __tablename__ = "entity_aliases"
    __table_args__ = (UniqueConstraint("normalized_alias", "entity_type", name="uq_entity_alias_type"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("entities.id", ondelete="RESTRICT"), nullable=False)
    alias: Mapped[str] = mapped_column(String(128), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EntityMention(Base):
    __tablename__ = "entity_mentions"
    __table_args__ = (Index("ix_entity_mentions_source", "source_item_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("entities.id", ondelete="RESTRICT"), nullable=False)
    source_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False)
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="RESTRICT"), nullable=False)
    mention_text: Mapped[str] = mapped_column(String(256), nullable=False)
    content_chunk_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("content_chunks.id", ondelete="RESTRICT"), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (Index("uq_tags_normalized", "normalized_name", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SourceTag(Base):
    __tablename__ = "source_tags"
    __table_args__ = (UniqueConstraint("source_item_id", "tag_id", name="uq_source_tag"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False)
    tag_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tags.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class KnowledgeCard(Base):
    __tablename__ = "knowledge_cards"
    __table_args__ = (
        Index("uq_knowledge_cards_org", "organization_run_id", unique=True),
        Index("uq_knowledge_cards_current", "source_item_id", unique=True, postgresql_where=text("is_current")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False)
    analysis_result_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("analysis_results.id", ondelete="RESTRICT"), nullable=False)
    organization_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization_runs.id", ondelete="RESTRICT"), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    summary_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class KnowledgeCardClaim(Base):
    __tablename__ = "knowledge_card_claims"
    __table_args__ = (UniqueConstraint("knowledge_card_id", "claim_id", name="uq_knowledge_card_claim"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_card_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("knowledge_cards.id", ondelete="RESTRICT"), nullable=False)
    claim_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)


class CommercialInsight(Base):
    __tablename__ = "commercial_insights"
    __table_args__ = (
        Index("uq_commercial_insights_org", "organization_run_id", unique=True),
        Index("uq_commercial_insights_current", "source_item_id", unique=True, postgresql_where=text("is_current")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False)
    analysis_result_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("analysis_results.id", ondelete="RESTRICT"), nullable=False)
    organization_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization_runs.id", ondelete="RESTRICT"), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    summary_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CommercialInsightClaim(Base):
    __tablename__ = "commercial_insight_claims"
    __table_args__ = (UniqueConstraint("commercial_insight_id", "claim_id", name="uq_commercial_insight_claim"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    commercial_insight_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("commercial_insights.id", ondelete="RESTRICT"), nullable=False)
    claim_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)


class CommercialInsightEntity(Base):
    __tablename__ = "commercial_insight_entities"
    __table_args__ = (UniqueConstraint("commercial_insight_id", "entity_id", name="uq_commercial_insight_entity"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    commercial_insight_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("commercial_insights.id", ondelete="RESTRICT"), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("entities.id", ondelete="RESTRICT"), nullable=False)


class ProjectCandidate(Base):
    __tablename__ = "project_candidates"
    __table_args__ = (Index("uq_project_candidates_org", "organization_run_id", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False)
    analysis_result_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("analysis_results.id", ondelete="RESTRICT"), nullable=False)
    organization_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization_runs.id", ondelete="RESTRICT"), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    summary_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PROPOSED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ProjectCandidateClaim(Base):
    __tablename__ = "project_candidate_claims"
    __table_args__ = (UniqueConstraint("project_candidate_id", "claim_id", name="uq_project_candidate_claim"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_candidate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("project_candidates.id", ondelete="RESTRICT"), nullable=False)
    claim_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="NEW")
    origin_project_candidate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("project_candidates.id", ondelete="RESTRICT"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ProjectSource(Base):
    __tablename__ = "project_sources"
    __table_args__ = (UniqueConstraint("project_id", "source_item_id", name="uq_project_source"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    source_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
