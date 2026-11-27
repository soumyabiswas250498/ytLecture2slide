"""Independent durable PDF generation state and publication metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pdf_generations",
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id"), primary_key=True),
        sa.Column("source_slide_generation", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("completed_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pdf_path", sa.String(1024), nullable=True),
        sa.Column("pdf_filename", sa.String(512), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("configuration", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pdf_generations_status", "pdf_generations", ["status"])
    op.create_index("ix_pdf_generations_completed_at", "pdf_generations", ["completed_at"])


def downgrade() -> None:
    op.drop_index("ix_pdf_generations_completed_at", table_name="pdf_generations")
    op.drop_index("ix_pdf_generations_status", table_name="pdf_generations")
    op.drop_table("pdf_generations")
