"""add salons.billed_plan (watermark by tariff)

Revision ID: c5e91a3f7b28
Revises: 4a8c707c63e0
Create Date: 2026-08-23

Смена тарифа начисляла доплату на КАЖДОЕ повышение, а понижение её не
кредитовало: цикл «повысил → понизил → повысил» раздувал следующий счёт
(QA: lite→business→lite→business→corporate дал доплату 2531 ₽ при нуле новых
мастеров). Планка по тарифу хранит уже покрытый уровень — доплачиваем только
за превышение, возврат на ранее оплаченный уровень бесплатен.

Бэкфилл: текущий тариф считаем покрытым (иначе первая же смена начислила бы
доплату за уже оплаченный уровень).
"""
from alembic import op
import sqlalchemy as sa

revision = "c5e91a3f7b28"
down_revision = "4a8c707c63e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("salons", sa.Column("billed_plan", sa.String(length=20), nullable=True))
    op.execute("UPDATE salons SET billed_plan = business_tier WHERE business_tier IS NOT NULL")


def downgrade() -> None:
    op.drop_column("salons", "billed_plan")
