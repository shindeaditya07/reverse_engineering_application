"""jobs.snapshot_id: the pinned snapshot a pipeline job reads

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("snapshot_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("jobs_snapshot_id_fkey", "jobs", "snapshots", ["snapshot_id"], ["id"])
    op.create_index(op.f("ix_jobs_snapshot_id"), "jobs", ["snapshot_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_jobs_snapshot_id"), table_name="jobs")
    op.drop_constraint("jobs_snapshot_id_fkey", "jobs", type_="foreignkey")
    op.drop_column("jobs", "snapshot_id")
