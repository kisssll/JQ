"""add is_hidden to salons (owner-reversible visibility toggle)

Revision ID: a2b3c4d5e6f7
Revises: b9c0d1e2f3a4
Create Date: 2026-07-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, None] = 'b9c0d1e2f3a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("salons", sa.Column(
        "is_hidden", sa.Boolean(), nullable=False, server_default="false"
    ))


def downgrade() -> None:
    op.drop_column("salons", "is_hidden")
