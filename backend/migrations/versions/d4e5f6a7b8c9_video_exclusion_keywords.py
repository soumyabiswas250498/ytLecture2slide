"""Add app_settings table and video exclusion classification columns."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d8e1f2a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column(
        "videos",
        sa.Column(
            "is_excluded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "videos",
        sa.Column("matched_exclusion_keywords", sa.Text(), nullable=True),
    )
    op.create_index("ix_videos_is_excluded", "videos", ["is_excluded"])


def downgrade() -> None:
    op.drop_index("ix_videos_is_excluded", table_name="videos")
    op.drop_column("videos", "matched_exclusion_keywords")
    op.drop_column("videos", "is_excluded")
    op.drop_table("app_settings")
