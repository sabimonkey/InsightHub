"""Point default LLM workflow routes at cloud deployments."""

from __future__ import annotations

from alembic import op
from sqlalchemy.orm import Session

from app.services.llm.cloud_defaults import apply_cloud_default_routes

revision = "h1a2b3c4d5e6"
down_revision = "g0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    session = Session(bind=bind)
    try:
        apply_cloud_default_routes(session)
    except RuntimeError:
        # Fresh installs without cloud secrets keep existing bootstrap until configured.
        session.rollback()
    finally:
        session.close()


def downgrade() -> None:
    pass
