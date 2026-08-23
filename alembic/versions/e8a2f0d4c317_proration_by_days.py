"""proration accrued by actual days of overage

Revision ID: e8a2f0d4c317
Revises: d7b4c1e05a92
Create Date: 2026-08-24

Доплата за рост штата начислялась одной суммой за ВЕСЬ остаток месяца в момент
найма и не откатывалась, если мастера убирали (QA B1: нанял и уволил двоих —
счёт вырос на 133 ₽ при том же штате). Переходим на начисление по дням
фактического превышения: помним, с какого момента действует текущий уровень
(proration_from) и какой он (prorated_masters), и капаем доплату за прошедший
отрезок при каждом изменении и перед выставлением счёта.

Бэкфилл: текущий уровень = оплаченный штат (превышения нет), отсчёт с сейчас.
Уже накопленную доплату не трогаем — она относится к прошлому периоду.
"""
from alembic import op
import sqlalchemy as sa

revision = "e8a2f0d4c317"
down_revision = "d7b4c1e05a92"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("salons", sa.Column("proration_from", sa.DateTime(timezone=True), nullable=True))
    op.add_column("salons", sa.Column("prorated_masters", sa.Integer(), nullable=False, server_default="0"))
    op.execute("UPDATE salons SET prorated_masters = billed_masters, proration_from = now()")


def downgrade() -> None:
    op.drop_column("salons", "prorated_masters")
    op.drop_column("salons", "proration_from")
