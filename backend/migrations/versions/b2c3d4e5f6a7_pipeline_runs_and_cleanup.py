"""add pipeline runs and video intermediate cleanup columns

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-27 15:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "videos",
        sa.Column(
            "intermediates_cleaned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "videos",
        sa.Column("intermediates_cleaned_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trigger_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_stage", sa.String(length=32), nullable=False),
        sa.Column("current_video_id", sa.Integer(), nullable=True),
        sa.Column("current_video_title", sa.String(length=512), nullable=True),
        sa.Column("current_stage_progress", sa.Float(), nullable=False),
        sa.Column("total_videos", sa.Integer(), nullable=False),
        sa.Column("completed_videos", sa.Integer(), nullable=False),
        sa.Column("excluded_videos", sa.Integer(), nullable=False),
        sa.Column("skipped_videos", sa.Integer(), nullable=False),
        sa.Column("failed_videos", sa.Integer(), nullable=False),
        sa.Column("cancelled_videos", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("reprocess_existing", sa.Boolean(), nullable=False),
        sa.Column("target_video_ids_json", sa.Text(), nullable=False),
        sa.Column("logs_json", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pipeline_runs_status", "pipeline_runs", ["status"])
    op.create_index("ix_pipeline_runs_created_at", "pipeline_runs", ["created_at"])

    op.create_table(
        "pipeline_run_videos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("video_title", sa.String(length=512), nullable=False),
        sa.Column("youtube_video_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("current_stage", sa.String(length=32), nullable=False),
        sa.Column("stage_progress", sa.Float(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("is_retryable", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("cleaned", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["pipeline_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "video_id", name="uq_pipeline_run_videos_run_video"),
    )
    op.create_index("ix_pipeline_run_videos_run_id", "pipeline_run_videos", ["run_id"])
    op.create_index("ix_pipeline_run_videos_video_id", "pipeline_run_videos", ["video_id"])


def downgrade() -> None:
    op.drop_index("ix_pipeline_run_videos_video_id", table_name="pipeline_run_videos")
    op.drop_index("ix_pipeline_run_videos_run_id", table_name="pipeline_run_videos")
    op.drop_table("pipeline_run_videos")
    op.drop_index("ix_pipeline_runs_created_at", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_status", table_name="pipeline_runs")
    op.drop_table("pipeline_runs")
    with op.batch_alter_table("videos") as batch_op:
        batch_op.drop_column("intermediates_cleaned_at")
        batch_op.drop_column("intermediates_cleaned")
