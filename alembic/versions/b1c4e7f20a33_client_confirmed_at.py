"""client confirmed booking

Revision ID: b1c4e7f20a33
Revises: a765971adfd9
Create Date: 2026-11-12 19:40:00.000000

Кнопка «Буду» в напоминании (решение 0020, п. 7). Подтверждение клиента —
отдельное поле, а не статус CONFIRMED: статус ставит салон, и он уже считается
выручкой (PAID_BOOKING_STATUSES), так что запись туда сдвинула бы деньги в
аналитике, зарплатах и обзоре.

Автогенерация, как и в a765971adfd9, предлагает полсотни посторонних правок
(NOT NULL у created_at и т. п.) — это давний дрейф схемы, к подтверждению он
не относится, и они выкинуты намеренно: менять прод заодно нельзя.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b1c4e7f20a33"
down_revision: Union[str, None] = "a765971adfd9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bookings",
        sa.Column("client_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bookings", "client_confirmed_at")
