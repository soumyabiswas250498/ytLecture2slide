"""Independent durable slide-processing intent and publication pointer."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ab61c4ea9012"
down_revision: str | None = "6ca8f2d915ab"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "slide_processing",
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id"), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("requested", sa.Boolean(), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        *[
            sa.Column(name, sa.Integer(), nullable=False)
            for name in (
                "input_count",
                "completed_count",
                "additional_count",
                "output_count",
                "duplicate_count",
                "reconstructed_count",
                "review_count",
                "retry_count",
            )
        ],
        sa.Column("configuration", sa.Text(), nullable=False),
        sa.Column("output_directory", sa.String(1024)),
        sa.Column("error", sa.Text()),
    )


def downgrade() -> None:
    op.drop_table("slide_processing")
