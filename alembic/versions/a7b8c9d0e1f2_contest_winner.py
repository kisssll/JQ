"""Победитель конкурса: подъём в каталоге со сроком

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
"""
import sqlalchemy as sa
from alembic import op

revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("salons", sa.Column("contest_winner_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("salons", "contest_winner_until")
