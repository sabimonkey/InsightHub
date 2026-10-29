"""Backfill USER-scoped automation markers on ask sessions and briefs."""

from alembic import op

revision = "g0a1b2c3d4e5"
down_revision = "f9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE ask_sessions
        SET system_scope = 'AUTOMATION_TEST'
        WHERE system_scope = 'USER'
          AND (
            title ILIKE 'e2e-%'
            OR title ILIKE '%e2e-%'
            OR title ILIKE '%e2e %'
            OR title ILIKE '%playwright%'
            OR title ILIKE '%R1 closure smoke%'
            OR title ILIKE '%release smoke%'
          )
        """
    )
    op.execute(
        """
        UPDATE briefs
        SET system_scope = 'AUTOMATION_TEST'
        WHERE system_scope = 'USER'
          AND (
            COALESCE(title, '') ILIKE '%e2e%'
            OR COALESCE(title, '') ILIKE '%smoke%'
            OR COALESCE(title, '') ILIKE '%playwright%'
          )
        """
    )


def downgrade() -> None:
    pass
