"""Persist channel_name and youtube_channel_id on videos and backfill from channels."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("videos", sa.Column("channel_name", sa.String(255), nullable=True))
    op.add_column("videos", sa.Column("youtube_channel_id", sa.String(64), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE videos
            SET
                channel_name = (
                    SELECT channels.name FROM channels WHERE channels.id = videos.channel_id
                ),
                youtube_channel_id = (
                    SELECT channels.youtube_channel_id
                    FROM channels
                    WHERE channels.id = videos.channel_id
                )
            WHERE channel_id IS NOT NULL
              AND EXISTS (SELECT 1 FROM channels WHERE channels.id = videos.channel_id)
            """
        )
    )


def downgrade() -> None:
    op.drop_column("videos", "youtube_channel_id")
    op.drop_column("videos", "channel_name")
