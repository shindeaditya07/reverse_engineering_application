"""claims.key: a stable producer id, unique per run, so a resumed run cannot duplicate a claim

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("claims", sa.Column("key", sa.Text(), nullable=True))
    op.execute("UPDATE claims SET key = id::text WHERE key IS NULL")
    op.alter_column("claims", "key", nullable=False)
    op.create_unique_constraint("uq_claim_run_key", "claims", ["run_id", "key"])


def downgrade() -> None:
    op.drop_constraint("uq_claim_run_key", "claims", type_="unique")
    op.drop_column("claims", "key")
