"""booking reschedule counters

Revision ID: a765971adfd9
Revises: 7c3a91e5d2b8
Create Date: 2026-11-12 15:23:13.796523

Перенос записи клиентом (решение 0020). Запись при переносе остаётся той же,
поэтому след переноса живёт в ней самой: сколько раз двигали и когда в
последний раз. Лимита нет — счётчик копит данные, по которым его решат.

Автогенерация заодно предлагала полсотни посторонних правок (NOT NULL у
created_at и т. п.) — это давний дрейф схемы, к переносу не относится, и
тащить его в эту миграцию значило бы менять прод вслепую.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a765971adfd9"
down_revision: Union[str, None] = "7c3a91e5d2b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bookings",
        sa.Column("rescheduled_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "bookings",
        sa.Column("rescheduled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bookings", "rescheduled_at")
    op.drop_column("bookings", "rescheduled_count")
