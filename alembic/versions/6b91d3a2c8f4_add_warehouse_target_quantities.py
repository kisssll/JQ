"""add target stock quantities to warehouse products

Revision ID: 6b91d3a2c8f4
Revises: f8c2a6d91b43
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6b91d3a2c8f4"
down_revision: Union[str, Sequence[str], None] = "f8c2a6d91b43"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "inventory_items",
        sa.Column("target_quantity", sa.Float(), server_default="0", nullable=False),
    )
    op.add_column(
        "equipment",
        sa.Column("target_quantity", sa.Float(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("equipment", "target_quantity")
    op.drop_column("inventory_items", "target_quantity")
