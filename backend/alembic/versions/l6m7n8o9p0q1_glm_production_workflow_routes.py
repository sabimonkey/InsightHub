"""Point production LLM workflow routes at SiliconFlow GLM-5.3-Flash (M-PIPELINE-R2)."""

from __future__ import annotations

from alembic import op
from sqlalchemy.orm import Session

from app.services.llm.cloud_defaults import apply_cloud_default_routes

revision = "l6m7n8o9p0q1"
down_revision = "k5l6m7n8o9p0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    session = Session(bind=bind)
    try:
        apply_cloud_default_routes(session)
    except RuntimeError:
        session.rollback()
    finally:
        session.close()


def downgrade() -> None:
    pass
