"""Narrow automation scope backfill to explicit e2e markers only."""

from alembic import op

revision = "f9a0b1c2d3e4"
down_revision = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None

PROTECTED = (
    "https://x.com/ai_suxiaole/status/2106663866235261360",
    "https://x.com/denziideng/status/2106939914566922451",
    "https://x.com/bkdgiffug/status/2106962081182363902",
)


def upgrade() -> None:
    protected = ", ".join(f"'{url}'" for url in PROTECTED)
    op.execute(
        f"""
        UPDATE source_items
        SET system_scope = 'USER'
        WHERE system_scope = 'AUTOMATION_TEST'
          AND display_name NOT ILIKE 'e2e-%'
          AND COALESCE(canonical_url, original_url) NOT IN ({protected})
        """
    )
    op.execute(
        """
        UPDATE ask_sessions
        SET system_scope = 'USER'
        WHERE system_scope = 'AUTOMATION_TEST'
          AND (title IS NULL OR title NOT ILIKE 'e2e-%')
        """
    )
    op.execute(
        """
        UPDATE briefs
        SET system_scope = 'USER'
        WHERE system_scope = 'AUTOMATION_TEST'
          AND (title IS NULL OR title NOT ILIKE 'e2e-%')
        """
    )


def downgrade() -> None:
    pass
