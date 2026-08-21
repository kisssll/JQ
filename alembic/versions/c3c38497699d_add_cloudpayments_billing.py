"""add cloudpayments billing (payments table + subscription fields on salons)

Оплата бизнес-подписок через CloudPayments. Новая таблица payments (одна
строка на попытку списания/возврата: верификация карты, первое списание по
подписке, плановое автосписание, ручная оплата) + поля на salons для
текущего статуса подписки (триал/актив/просрочено/отменено, дата окончания
доступа, id подписки CloudPayments, автопродление вкл/выкл).

Два разных подхода к enum-типам, оба по прецеденту существующих миграций:
- salonsubscriptionstatus (ADD COLUMN к уже существующей таблице salons) —
  создаём тип явно (checkfirst) + create_type=False на колонке, как в
  b7c1d9e0f2a3_salon_moderation_status.py. Для ALTER TABLE ADD COLUMN
  SQLAlchemy сам тип не создаёт.
- paymentkind/paymentstatus (только в новой таблице payments, CREATE TABLE) —
  НЕ создаём заранее: SQLAlchemy создаёт PG ENUM автоматически как часть
  CREATE TABLE (см. 78a6031c004b_equipment_and_warehouse_requests.py).
  Предварительное создание + create_type=False здесь ловит
  DuplicateObjectError — проверено на этой миграции.

Бэкфилл не нужен: существующие салоны получают server_default=NONE
(subscription_status) — оплата для них просто ещё не подключена, задним
числом в trialing/active их не переводим.

Revision ID: c3c38497699d
Revises: 3024a7a5be87
Create Date: 2026-08-21
"""
from alembic import op
import sqlalchemy as sa

revision = "c3c38497699d"
down_revision = "3024a7a5be87"
branch_labels = None
depends_on = None

# Значения enum — ИМЕНА членов (конвенция проекта: SQLAlchemy хранит имя).
_subscription_status = sa.Enum(
    "NONE", "TRIALING", "ACTIVE", "PAST_DUE", "CANCELED",
    name="salonsubscriptionstatus",
)


def upgrade() -> None:
    _subscription_status.create(op.get_bind(), checkfirst=True)
    op.add_column("salons", sa.Column(
        "subscription_status",
        sa.Enum("NONE", "TRIALING", "ACTIVE", "PAST_DUE", "CANCELED",
                name="salonsubscriptionstatus", create_type=False),
        server_default="NONE", nullable=False,
    ))
    op.add_column("salons", sa.Column(
        "auto_renew", sa.Boolean(), server_default="false", nullable=False,
    ))
    op.add_column("salons", sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("salons", sa.Column("subscription_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("salons", sa.Column("cp_subscription_id", sa.String(length=50), nullable=True))
    op.add_column("salons", sa.Column("card_last4", sa.String(length=4), nullable=True))

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "salon_id", sa.Integer(),
            sa.ForeignKey("salons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan", sa.String(length=20), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("VERIFICATION", "SUBSCRIPTION_INITIAL", "RECURRENT", "MANUAL", "REFUND",
                    name="paymentkind"),
            nullable=False,
        ),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="RUB", nullable=False),
        sa.Column("target_amount", sa.Float(), nullable=True),
        sa.Column("invoice_id", sa.String(length=50), nullable=True),
        sa.Column("cp_transaction_id", sa.String(length=50), nullable=True),
        sa.Column(
            "status",
            sa.Enum("PENDING", "SUCCEEDED", "FAILED", "REFUNDED", name="paymentstatus"),
            server_default="PENDING", nullable=False,
        ),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_payments_salon_id", "payments", ["salon_id"])
    op.create_index("ix_payments_cp_transaction_id", "payments", ["cp_transaction_id"])
    op.create_index("ix_payments_invoice_id", "payments", ["invoice_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_payments_invoice_id", table_name="payments")
    op.drop_index("ix_payments_cp_transaction_id", table_name="payments")
    op.drop_index("ix_payments_salon_id", table_name="payments")
    op.drop_table("payments")
    op.execute("DROP TYPE IF EXISTS paymentkind")
    op.execute("DROP TYPE IF EXISTS paymentstatus")

    op.drop_column("salons", "card_last4")
    op.drop_column("salons", "cp_subscription_id")
    op.drop_column("salons", "subscription_expires_at")
    op.drop_column("salons", "trial_ends_at")
    op.drop_column("salons", "auto_renew")
    op.drop_column("salons", "subscription_status")
    _subscription_status.drop(op.get_bind(), checkfirst=True)
