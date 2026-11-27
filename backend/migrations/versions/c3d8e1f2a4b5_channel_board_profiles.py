"""Persistent channel-specific smartboard crop and perspective profiles."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d8e1f2a4b5"
down_revision: str | None = "ab61c4ea9012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "channel_board_profiles",
        sa.Column(
            "channel_id",
            sa.Integer(),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("crop_left", sa.Float(), nullable=False),
        sa.Column("crop_top", sa.Float(), nullable=False),
        sa.Column("crop_right", sa.Float(), nullable=False),
        sa.Column("crop_bottom", sa.Float(), nullable=False),
        sa.Column("corners_json", sa.Text(), nullable=True),
        sa.Column("reference_width", sa.Integer(), nullable=True),
        sa.Column("reference_height", sa.Integer(), nullable=True),
        sa.Column("validated", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("channel_board_profiles")
