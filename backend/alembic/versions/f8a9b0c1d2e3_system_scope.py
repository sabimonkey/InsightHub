"""Add system_scope for automation test isolation."""

from alembic import op
import sqlalchemy as sa

revision = "f8a9b0c1d2e3"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None

PROTECTED = (
    "https://x.com/ai_suxiaole/status/2106663866235261360",
    "https://x.com/denziideng/status/2106939914566922451",
    "https://x.com/bkdgiffug/status/2106962081182363902",
)


def upgrade() -> None:
    op.add_column("source_items", sa.Column("system_scope", sa.String(length=32), server_default="USER", nullable=False))
    op.add_column("ask_sessions", sa.Column("system_scope", sa.String(length=32), server_default="USER", nullable=False))
    op.add_column("briefs", sa.Column("system_scope", sa.String(length=32), server_default="USER", nullable=False))
    protected = ", ".join(f"'{url}'" for url in PROTECTED)
    op.execute(
        f"""
        UPDATE source_items
        SET system_scope = 'AUTOMATION_TEST'
        WHERE display_name ILIKE 'e2e-%'
           OR display_name ILIKE '%playwright%'
           OR display_name ILIKE '%R1 closure smoke%'
        AND COALESCE(canonical_url, original_url) NOT IN ({protected})
        """
    )
    op.execute(
        """
        UPDATE ask_sessions
        SET system_scope = 'AUTOMATION_TEST'
        WHERE title ILIKE 'e2e-%' OR title ILIKE '%smoke%'
        """
    )
    op.execute(
        """
        UPDATE briefs
        SET system_scope = 'AUTOMATION_TEST'
        WHERE title ILIKE 'e2e-%' OR title ILIKE '%smoke%'
        """
    )


def downgrade() -> None:
    op.drop_column("briefs", "system_scope")
    op.drop_column("ask_sessions", "system_scope")
    op.drop_column("source_items", "system_scope")
