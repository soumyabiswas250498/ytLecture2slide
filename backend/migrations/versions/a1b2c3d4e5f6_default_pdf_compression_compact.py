"""Update persisted default PDF compression setting to compact (JPEG 85)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE app_settings
            SET value_json = '{"compression": "compact"}'
            WHERE key = 'pdf_generation_settings'
              AND value_json LIKE '%"lossless"%'
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE app_settings
            SET value_json = '{"compression": "lossless"}'
            WHERE key = 'pdf_generation_settings'
              AND value_json LIKE '%"compact"%'
            """
        )
    )
