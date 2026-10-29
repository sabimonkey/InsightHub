"""Persist versioned global cover prompt configuration."""

from alembic import op
import sqlalchemy as sa


revision = "n0p1q2r3s4t5"
down_revision = "m9n0o1p2q3r4"
branch_labels = None
depends_on = None

DEFAULT_PROMPT = (
    "Create a striking horizontal 16:9 research cover. Choose one topic-fitting direction—cyberpunk, advanced technology, "
    "science fiction, futurism, anime illustration, or premium 3D/CGI—and at most one complementary style. Make the article's "
    "real subject large, unmistakable, and directly relevant. Use cinematic light, purposeful rich detail, depth, a clear "
    "silhouette, and strong contrast readable at card size. Choose varied topic-led colors (blue, cyan, violet, pink, red, "
    "silver-gray, black-gold, neutral, or warm only when appropriate); never default to orange. Avoid washed-out scenes, "
    "excess empty space, tiny subjects, unrelated robots, chips, or future cities, decorative text, random UI glyphs, logos, "
    "and watermarks. Follow supplied topic and context; invent no claims."
)


def upgrade() -> None:
    op.create_table(
        "cover_prompt_revisions",
        sa.Column("revision", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "uq_cover_prompt_revisions_active",
        "cover_prompt_revisions",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE"),
        sqlite_where=sa.text("is_active = 1"),
    )
    op.execute(
        sa.text(
            "INSERT INTO cover_prompt_revisions (revision, prompt, version, is_active) "
            "VALUES (1, :prompt, 'global-cover-r1', TRUE)"
        ).bindparams(prompt=DEFAULT_PROMPT)
    )


def downgrade() -> None:
    op.drop_index("uq_cover_prompt_revisions_active", table_name="cover_prompt_revisions")
    op.drop_table("cover_prompt_revisions")
