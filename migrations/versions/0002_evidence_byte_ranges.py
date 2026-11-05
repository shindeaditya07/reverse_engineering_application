"""evidence byte ranges for files that cannot be decoded (EVD-1.5)

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_CHECK = (
    "kind <> 'file_range' OR (path IS NOT NULL AND start_line >= 1 "
    "AND end_line >= start_line AND end_line - start_line + 1 <= 40)"
)
NEW_CHECK = (
    "kind <> 'file_range' OR (path IS NOT NULL AND ("
    "(start_line IS NOT NULL AND end_line IS NOT NULL AND start_line >= 1 "
    "AND end_line >= start_line AND end_line - start_line + 1 <= 40 "
    "AND start_byte IS NULL AND end_byte IS NULL) OR "
    "(start_byte IS NOT NULL AND end_byte IS NOT NULL AND start_byte >= 0 "
    "AND end_byte > start_byte "
    "AND start_line IS NULL AND end_line IS NULL)))"
)


def upgrade() -> None:
    op.add_column("evidence", sa.Column("start_byte", sa.BigInteger(), nullable=True))
    op.add_column("evidence", sa.Column("end_byte", sa.BigInteger(), nullable=True))
    op.drop_constraint("file_range_valid", "evidence", type_="check")
    op.create_check_constraint("file_range_valid", "evidence", NEW_CHECK)


def downgrade() -> None:
    in_use = op.get_bind().execute(
        sa.text("SELECT count(*) FROM evidence WHERE start_byte IS NOT NULL")
    )
    if in_use.scalar_one():
        raise RuntimeError("cannot downgrade: byte-range evidence exists and would be lost")
    op.drop_constraint("file_range_valid", "evidence", type_="check")
    op.create_check_constraint("file_range_valid", "evidence", OLD_CHECK)
    op.drop_column("evidence", "end_byte")
    op.drop_column("evidence", "start_byte")
