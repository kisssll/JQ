"""add optional upper bound to service prices

Revision ID: d8e9f0a1b2c3
Revises: c4f8a1e6b207
Create Date: 2026-09-11 21:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, None] = "c4f8a1e6b207"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Some installations were initialized with Base.metadata.create_all and
    # then stamped as current. Keep the migration safe for that schema too.
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("services")}
    if "price_max" not in columns:
        op.add_column("services", sa.Column("price_max", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("services", "price_max")
