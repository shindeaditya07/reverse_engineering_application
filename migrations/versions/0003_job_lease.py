"""job lease columns so a sweeper can tell a dead worker from a slow one (OPS-1.1)

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK = "status <> 'running' OR (locked_at IS NOT NULL AND locked_by IS NOT NULL)"


def upgrade() -> None:
    op.add_column("jobs", sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("locked_by", sa.String(64), nullable=True))
    op.create_check_constraint("running_has_lease", "jobs", CHECK)
    op.create_index("ix_jobs_claim", "jobs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_claim", table_name="jobs")
    op.drop_constraint("running_has_lease", "jobs", type_="check")
    op.drop_column("jobs", "locked_by")
    op.drop_column("jobs", "locked_at")
