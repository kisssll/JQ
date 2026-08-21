"""switch billing to t-kassa (provider-neutral column names + subscription amount)

Оказалось, что реально подключён Т-Касса (Т-Бизнес/Тинькофф), а не
CloudPayments — переименовываем провайдер-специфичные колонки на нейтральные
имена (у Т-Кассы нет объекта «подписка», регулярные списания планируем сами,
поэтому нужна ещё и постоянная сумма ежемесячного платежа на салоне).

payments.cp_transaction_id -> payments.provider_transaction_id
salons.cp_subscription_id  -> salons.recurring_token (хранит RebillId Т-Кассы)
+ salons.subscription_amount (сумма месячного платежа, руб.) — нужна для
  планового списания через Charge, у Т-Кассы это не хранится на их стороне.

Revision ID: c187927238c7
Revises: c3c38497699d
Create Date: 2026-08-21
"""
from alembic import op
import sqlalchemy as sa

revision = "c187927238c7"
down_revision = "c3c38497699d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("payments", "cp_transaction_id", new_column_name="provider_transaction_id")
    op.drop_index("ix_payments_cp_transaction_id", table_name="payments")
    op.create_index("ix_payments_provider_transaction_id", "payments", ["provider_transaction_id"])

    op.alter_column("salons", "cp_subscription_id", new_column_name="recurring_token")
    op.add_column("salons", sa.Column("subscription_amount", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("salons", "subscription_amount")
    op.alter_column("salons", "recurring_token", new_column_name="cp_subscription_id")

    op.drop_index("ix_payments_provider_transaction_id", table_name="payments")
    op.alter_column("payments", "provider_transaction_id", new_column_name="cp_transaction_id")
    op.create_index("ix_payments_cp_transaction_id", "payments", ["cp_transaction_id"])
