"""add payments.months (prepay for several months ahead)

Revision ID: a3f5d2c81b40
Revises: f2c8a41d7b93
Create Date: 2026-08-23

Предоплата вперёд: раньше платёж всегда продлевал доступ ровно на 30 дней,
и заплатить за несколько месяцев сразу было нельзя. Храним оплаченный срок
в самом платеже — при подтверждении продлеваем на 30 × months.
"""
from alembic import op
import sqlalchemy as sa

revision = "a3f5d2c81b40"
down_revision = "f2c8a41d7b93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("months", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    op.drop_column("payments", "months")
