"""llm workflow routes

Revision ID: d1a3c5e70f28
Revises: c8d2e5f03b19
Create Date: 2026-10-08 12:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1a3c5e70f28"
down_revision: Union[str, Sequence[str], None] = "c8d2e5f03b19"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_WORKFLOWS = ("ANALYSIS", "ASK_PLANNER", "ASK_ANSWER", "BRIEF")


def upgrade() -> None:
    op.create_table(
        "llm_workflow_routes",
        sa.Column("workflow", sa.String(length=32), primary_key=True),
        sa.Column("provider_type", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    table = sa.table(
        "llm_workflow_routes",
        sa.column("workflow", sa.String),
        sa.column("provider_type", sa.String),
    )
    op.bulk_insert(table, [{"workflow": name, "provider_type": "LOCAL_OPENAI_COMPATIBLE"} for name in _WORKFLOWS])


def downgrade() -> None:
    op.drop_table("llm_workflow_routes")
