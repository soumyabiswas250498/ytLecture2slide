"""Independent persistent frame extraction state.

Revision ID: 6ca8f2d915ab
Revises: b0f3f4fb90a4
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6ca8f2d915ab"
down_revision: str | None = "b0f3f4fb90a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "extractions",
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id"), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("requested", sa.Boolean(), nullable=False),
        sa.Column("interval_seconds", sa.Float(), nullable=False),
        sa.Column("frame_count", sa.Integer(), nullable=False),
        sa.Column("expected_count", sa.Integer()),
        sa.Column("frame_directory", sa.String(1024)),
        sa.Column("manifest_path", sa.String(1024)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
    )


def downgrade() -> None:
    op.drop_table("extractions")
