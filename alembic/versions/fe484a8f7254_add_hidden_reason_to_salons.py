"""add hidden_reason to salons

Скрытие салона по неоплате (см. app.tasks.expire_unpaid_salons) переиспользует
существующий salons.is_hidden, но нужно отличать «скрыт автоматически за
неоплату» от «скрыт вручную владельцем» — иначе после оплаты не понять, можно
ли автоматически вернуть салон в каталог, а кнопка «показать» в кабинете
могла бы случайно обойти неоплаченную подписку.

Revision ID: fe484a8f7254
Revises: b12982aa0151
Create Date: 2026-08-22
"""
from alembic import op
import sqlalchemy as sa

revision = "fe484a8f7254"
down_revision = "b12982aa0151"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("salons", sa.Column("hidden_reason", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("salons", "hidden_reason")
