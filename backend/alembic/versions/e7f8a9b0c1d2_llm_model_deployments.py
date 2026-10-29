"""llm model deployments

Revision ID: e7f8a9b0c1d2
Revises: d1a3c5e70f28
Create Date: 2026-10-11 16:10:00.000000

"""
from __future__ import annotations

import json
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "d1a3c5e70f28"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_WORKFLOWS = ("ANALYSIS", "ASK_PLANNER", "ASK_ANSWER", "BRIEF")
_LOCAL_TYPE = "LOCAL_OPENAI_COMPATIBLE"
_DEFAULT_LOCAL_CAPS = {
    "supports_json_schema": True,
    "supports_json_object": False,
    "supports_streaming": False,
    "supports_multimodal": False,
    "supports_reasoning": False,
    "context_window": 32768,
    "default_max_output_tokens": None,
    "timeout_seconds": None,
}


def upgrade() -> None:
    op.create_table(
        "llm_model_deployments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_config_id", UUID(as_uuid=True), sa.ForeignKey("llm_provider_configs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("model_id", sa.String(length=512), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("capabilities_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_llm_model_deployments_provider", "llm_model_deployments", ["provider_config_id"])

    op.add_column("llm_workflow_routes", sa.Column("deployment_id", UUID(as_uuid=True), nullable=True))

    conn = op.get_bind()
    providers = conn.execute(
        sa.text(
            "SELECT id, provider_type, model, capabilities_json, is_local FROM llm_provider_configs"
        )
    ).mappings().all()
    provider_by_type = {row["provider_type"]: row for row in providers}
    deployment_by_provider: dict[str, uuid.UUID] = {}

    for row in providers:
        model_id = (row["model"] or "").strip()
        if not model_id:
            continue
        dep_id = uuid.uuid4()
        caps = row["capabilities_json"] if row["capabilities_json"] else {}
        if row["provider_type"] == _LOCAL_TYPE and not caps:
            caps = dict(_DEFAULT_LOCAL_CAPS)
        if row["is_local"] and row["provider_type"] == _LOCAL_TYPE:
            caps = {**_DEFAULT_LOCAL_CAPS, **(caps or {})}
        conn.execute(
            sa.text(
                """
                INSERT INTO llm_model_deployments
                (id, provider_config_id, display_name, model_id, enabled, capabilities_json, created_at, updated_at)
                VALUES (:id, :provider_config_id, :display_name, :model_id, true, CAST(:caps AS jsonb), NOW(), NOW())
                """
            ),
            {
                "id": dep_id,
                "provider_config_id": row["id"],
                "display_name": model_id,
                "model_id": model_id,
                "caps": json.dumps(caps),
            },
        )
        deployment_by_provider[row["provider_type"]] = dep_id

    routes = conn.execute(sa.text("SELECT workflow, provider_type FROM llm_workflow_routes")).mappings().all()
    local_dep = deployment_by_provider.get(_LOCAL_TYPE)
    for route in routes:
        dep_id = deployment_by_provider.get(route["provider_type"]) or local_dep
        if dep_id is None and route["provider_type"] == _LOCAL_TYPE:
            prov = provider_by_type.get(_LOCAL_TYPE)
            if prov is not None:
                dep_id = uuid.uuid4()
                model_id = (prov["model"] or "qwen2.5-14b-instruct").strip() or "qwen2.5-14b-instruct"
                conn.execute(
                    sa.text(
                        """
                        INSERT INTO llm_model_deployments
                        (id, provider_config_id, display_name, model_id, enabled, capabilities_json, created_at, updated_at)
                        VALUES (:id, :provider_config_id, :display_name, :model_id, true, CAST(:caps AS jsonb), NOW(), NOW())
                        """
                    ),
                    {
                        "id": dep_id,
                        "provider_config_id": prov["id"],
                        "display_name": model_id,
                        "model_id": model_id,
                        "caps": json.dumps(_DEFAULT_LOCAL_CAPS),
                    },
                )
                deployment_by_provider[_LOCAL_TYPE] = dep_id
        if dep_id is not None:
            conn.execute(
                sa.text("UPDATE llm_workflow_routes SET deployment_id = :dep WHERE workflow = :workflow"),
                {"dep": dep_id, "workflow": route["workflow"]},
            )

    if local_dep is None:
        local_dep = deployment_by_provider.get(_LOCAL_TYPE)
    if local_dep is not None:
        for workflow in _WORKFLOWS:
            conn.execute(
                sa.text(
                    """
                    UPDATE llm_workflow_routes SET deployment_id = :dep
                    WHERE workflow = :workflow AND deployment_id IS NULL
                    """
                ),
                {"dep": local_dep, "workflow": workflow},
            )

    op.alter_column("llm_workflow_routes", "deployment_id", nullable=False)
    op.create_foreign_key(
        "fk_llm_workflow_routes_deployment",
        "llm_workflow_routes",
        "llm_model_deployments",
        ["deployment_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_column("llm_workflow_routes", "provider_type")


def downgrade() -> None:
    op.add_column("llm_workflow_routes", sa.Column("provider_type", sa.String(length=64), nullable=True))
    conn = op.get_bind()
    routes = conn.execute(
        sa.text(
            """
            SELECT r.workflow, p.provider_type
            FROM llm_workflow_routes r
            JOIN llm_model_deployments d ON d.id = r.deployment_id
            JOIN llm_provider_configs p ON p.id = d.provider_config_id
            """
        )
    ).mappings().all()
    for route in routes:
        conn.execute(
            sa.text("UPDATE llm_workflow_routes SET provider_type = :ptype WHERE workflow = :workflow"),
            {"ptype": route["provider_type"], "workflow": route["workflow"]},
        )
    for workflow in _WORKFLOWS:
        conn.execute(
            sa.text(
                """
                UPDATE llm_workflow_routes SET provider_type = :ptype
                WHERE workflow = :workflow AND provider_type IS NULL
                """
            ),
            {"ptype": _LOCAL_TYPE, "workflow": workflow},
        )
    op.alter_column("llm_workflow_routes", "provider_type", nullable=False)
    op.drop_constraint("fk_llm_workflow_routes_deployment", "llm_workflow_routes", type_="foreignkey")
    op.drop_column("llm_workflow_routes", "deployment_id")
    op.drop_index("ix_llm_model_deployments_provider", table_name="llm_model_deployments")
    op.drop_table("llm_model_deployments")
