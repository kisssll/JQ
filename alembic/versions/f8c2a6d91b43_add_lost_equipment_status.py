"""add lost equipment status

Revision ID: f8c2a6d91b43
Revises: c21e9a7b4d62
"""
from typing import Sequence, Union

from alembic import op


revision: str = "f8c2a6d91b43"
down_revision: Union[str, Sequence[str], None] = "c21e9a7b4d62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE equipmentstatus ADD VALUE IF NOT EXISTS 'LOST'")


def downgrade() -> None:
    op.execute(
        "UPDATE equipment SET status = 'WORKING' WHERE status = 'LOST'"
    )
    op.execute("ALTER TABLE equipment ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TYPE equipmentstatus RENAME TO equipmentstatus_old")
    op.execute(
        "CREATE TYPE equipmentstatus AS ENUM ('WORKING', 'BROKEN')"
    )
    op.execute(
        "ALTER TABLE equipment ALTER COLUMN status TYPE equipmentstatus "
        "USING status::text::equipmentstatus"
    )
    op.execute(
        "ALTER TABLE equipment ALTER COLUMN status SET DEFAULT 'WORKING'"
    )
    op.execute("DROP TYPE equipmentstatus_old")
