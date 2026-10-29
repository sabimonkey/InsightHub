"""m5 knowledge organization

Revision ID: f5c9d2e81b36
Revises: e4b8c1d90a27
Create Date: 2026-09-25 15:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f5c9d2e81b36"
down_revision: Union[str, Sequence[str], None] = "e4b8c1d90a27"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid():
    return postgresql.UUID(as_uuid=True)


def _ts():
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "organization_runs",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("source_item_id", _uuid(), nullable=False),
        sa.Column("analysis_run_id", _uuid(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        _ts(),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_organization_runs_source_item_id", "organization_runs", ["source_item_id"])
    op.create_index("uq_organization_runs_current", "organization_runs", ["source_item_id"], unique=True, postgresql_where=sa.text("is_current"))
    op.create_index("uq_organization_runs_analysis_success", "organization_runs", ["analysis_run_id"], unique=True, postgresql_where=sa.text("status IN ('SUCCEEDED', 'PARTIAL')"))
    op.create_table(
        "categories",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("is_system_default", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        _ts(),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("uq_categories_slug", "categories", ["slug"], unique=True)
    op.execute(
        """
        INSERT INTO categories (id, name, slug, display_order, is_system_default, is_active)
        VALUES
          (gen_random_uuid(), '发现项目', 'project_discovery', 1, true, true),
          (gen_random_uuid(), '商业', 'business', 2, true, true),
          (gen_random_uuid(), '知识', 'knowledge', 3, true, true),
          (gen_random_uuid(), '其他', 'other', 4, true, true)
        ON CONFLICT (slug) DO NOTHING
        """
    )
    op.create_table(
        "source_category_assignments",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("source_item_id", _uuid(), nullable=False),
        sa.Column("category_id", _uuid(), nullable=False),
        sa.Column("organization_run_id", _uuid(), nullable=True),
        sa.Column("analysis_run_id", _uuid(), nullable=True),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        _ts(),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_run_id"], ["organization_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="RESTRICT"),
    )
    op.create_index("uq_source_category_primary", "source_category_assignments", ["source_item_id"], unique=True, postgresql_where=sa.text("is_primary AND status = 'ACTIVE'"))
    op.create_index("uq_source_category_system_run", "source_category_assignments", ["source_item_id", "category_id", "organization_run_id"], unique=True, postgresql_where=sa.text("origin = 'SYSTEM_ANALYSIS' AND organization_run_id IS NOT NULL"))
    op.create_index("uq_source_category_user", "source_category_assignments", ["source_item_id", "category_id"], unique=True, postgresql_where=sa.text("origin = 'USER'"))
    op.create_table(
        "topics",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("normalized_name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("parent_id", _uuid(), nullable=True),
        sa.Column("merged_into_topic_id", _uuid(), nullable=True),
        _ts(),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["topics.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["merged_into_topic_id"], ["topics.id"], ondelete="RESTRICT"),
    )
    op.create_index("uq_topics_normalized_open", "topics", ["normalized_name"], unique=True, postgresql_where=sa.text("merged_into_topic_id IS NULL"))
    op.create_table(
        "topic_aliases",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("topic_id", _uuid(), nullable=False),
        sa.Column("alias", sa.String(128), nullable=False),
        sa.Column("normalized_alias", sa.String(128), nullable=False),
        _ts(),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="RESTRICT"),
    )
    op.create_index("uq_topic_aliases_normalized", "topic_aliases", ["normalized_alias"], unique=True)
    op.create_table(
        "source_topic_assignments",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("source_item_id", _uuid(), nullable=False),
        sa.Column("topic_id", _uuid(), nullable=False),
        sa.Column("organization_run_id", _uuid(), nullable=True),
        sa.Column("analysis_run_id", _uuid(), nullable=True),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        _ts(),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_run_id"], ["organization_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="RESTRICT"),
    )
    op.create_index("uq_source_topic_system_run", "source_topic_assignments", ["source_item_id", "topic_id", "organization_run_id"], unique=True, postgresql_where=sa.text("origin = 'SYSTEM_ANALYSIS' AND organization_run_id IS NOT NULL"))
    op.create_index("uq_source_topic_user", "source_topic_assignments", ["source_item_id", "topic_id"], unique=True, postgresql_where=sa.text("origin = 'USER'"))
    op.create_table(
        "entities",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("normalized_name", sa.String(128), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("merged_into_entity_id", _uuid(), nullable=True),
        _ts(),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["merged_into_entity_id"], ["entities.id"], ondelete="RESTRICT"),
    )
    op.create_index("uq_entities_name_type_open", "entities", ["normalized_name", "entity_type"], unique=True, postgresql_where=sa.text("merged_into_entity_id IS NULL"))
    op.create_table(
        "entity_aliases",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("entity_id", _uuid(), nullable=False),
        sa.Column("alias", sa.String(128), nullable=False),
        sa.Column("normalized_alias", sa.String(128), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        _ts(),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("normalized_alias", "entity_type", name="uq_entity_alias_type"),
    )
    op.create_table(
        "entity_mentions",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("entity_id", _uuid(), nullable=False),
        sa.Column("source_item_id", _uuid(), nullable=False),
        sa.Column("analysis_run_id", _uuid(), nullable=False),
        sa.Column("mention_text", sa.String(256), nullable=False),
        sa.Column("content_chunk_id", _uuid(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        _ts(),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["content_chunk_id"], ["content_chunks.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_entity_mentions_source", "entity_mentions", ["source_item_id"])
    op.create_table(
        "tags",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("normalized_name", sa.String(64), nullable=False),
        _ts(),
    )
    op.create_index("uq_tags_normalized", "tags", ["normalized_name"], unique=True)
    op.create_table(
        "source_tags",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("source_item_id", _uuid(), nullable=False),
        sa.Column("tag_id", _uuid(), nullable=False),
        _ts(),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("source_item_id", "tag_id", name="uq_source_tag"),
    )
    op.create_table(
        "knowledge_cards",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("source_item_id", _uuid(), nullable=False),
        sa.Column("analysis_result_id", _uuid(), nullable=False),
        sa.Column("organization_run_id", _uuid(), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("summary_snapshot", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        _ts(),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["analysis_result_id"], ["analysis_results.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_run_id"], ["organization_runs.id"], ondelete="RESTRICT"),
    )
    op.create_index("uq_knowledge_cards_org", "knowledge_cards", ["organization_run_id"], unique=True)
    op.create_index("uq_knowledge_cards_current", "knowledge_cards", ["source_item_id"], unique=True, postgresql_where=sa.text("is_current"))
    op.create_table(
        "knowledge_card_claims",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("knowledge_card_id", _uuid(), nullable=False),
        sa.Column("claim_id", _uuid(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["knowledge_card_id"], ["knowledge_cards.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("knowledge_card_id", "claim_id", name="uq_knowledge_card_claim"),
    )
    op.create_table(
        "commercial_insights",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("source_item_id", _uuid(), nullable=False),
        sa.Column("analysis_result_id", _uuid(), nullable=False),
        sa.Column("organization_run_id", _uuid(), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("summary_snapshot", sa.Text(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        _ts(),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["analysis_result_id"], ["analysis_results.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_run_id"], ["organization_runs.id"], ondelete="RESTRICT"),
    )
    op.create_index("uq_commercial_insights_org", "commercial_insights", ["organization_run_id"], unique=True)
    op.create_index("uq_commercial_insights_current", "commercial_insights", ["source_item_id"], unique=True, postgresql_where=sa.text("is_current"))
    op.create_table(
        "commercial_insight_claims",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("commercial_insight_id", _uuid(), nullable=False),
        sa.Column("claim_id", _uuid(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["commercial_insight_id"], ["commercial_insights.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("commercial_insight_id", "claim_id", name="uq_commercial_insight_claim"),
    )
    op.create_table(
        "commercial_insight_entities",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("commercial_insight_id", _uuid(), nullable=False),
        sa.Column("entity_id", _uuid(), nullable=False),
        sa.ForeignKeyConstraint(["commercial_insight_id"], ["commercial_insights.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("commercial_insight_id", "entity_id", name="uq_commercial_insight_entity"),
    )
    op.create_table(
        "project_candidates",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("source_item_id", _uuid(), nullable=False),
        sa.Column("analysis_result_id", _uuid(), nullable=False),
        sa.Column("organization_run_id", _uuid(), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("summary_snapshot", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        _ts(),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["analysis_result_id"], ["analysis_results.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_run_id"], ["organization_runs.id"], ondelete="RESTRICT"),
    )
    op.create_index("uq_project_candidates_org", "project_candidates", ["organization_run_id"], unique=True)
    op.create_table(
        "project_candidate_claims",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("project_candidate_id", _uuid(), nullable=False),
        sa.Column("claim_id", _uuid(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["project_candidate_id"], ["project_candidates.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("project_candidate_id", "claim_id", name="uq_project_candidate_claim"),
    )
    op.create_table(
        "projects",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("origin_project_candidate_id", _uuid(), nullable=True),
        _ts(),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["origin_project_candidate_id"], ["project_candidates.id"], ondelete="RESTRICT"),
    )
    op.create_table(
        "project_sources",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("project_id", _uuid(), nullable=False),
        sa.Column("source_item_id", _uuid(), nullable=False),
        _ts(),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("project_id", "source_item_id", name="uq_project_source"),
    )


def downgrade() -> None:
    for name in (
        "project_sources",
        "projects",
        "project_candidate_claims",
        "project_candidates",
        "commercial_insight_entities",
        "commercial_insight_claims",
        "commercial_insights",
        "knowledge_card_claims",
        "knowledge_cards",
        "source_tags",
        "tags",
        "entity_mentions",
        "entity_aliases",
        "entities",
        "source_topic_assignments",
        "topic_aliases",
        "topics",
        "source_category_assignments",
        "categories",
        "organization_runs",
    ):
        op.drop_table(name)
