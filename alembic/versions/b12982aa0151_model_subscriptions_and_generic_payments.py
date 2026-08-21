"""model subscriptions (users) + generalize payments to salon-or-user

Публикация салона теперь требует выбранного тарифа (subscription_status !=
NONE), а не только модерации — но это чисто прикладная проверка в коде, схему
не трогает. Здесь — вторая половина: то же самое для «модели» (User),
плюс payments.salon_id становится nullable и добавляется payments.user_id,
чтобы одна и та же таблица платежей обслуживала обоих плательщиков.

users.subscription_tier/subscription_expires_at уже существовали (задел под
эту фичу с самого начала) — добавляем то, чего не хватало: статус подписки,
автопродление, конец триала, токен на автосписание, сумму, маску карты —
один в один с тем, что уже есть на salons (см. c3c38497699d/c187927238c7).

Revision ID: b12982aa0151
Revises: c187927238c7
Create Date: 2026-08-22
"""
from alembic import op
import sqlalchemy as sa

revision = "b12982aa0151"
down_revision = "c187927238c7"
branch_labels = None
depends_on = None

_STATUS_VALUES = ("NONE", "TRIALING", "ACTIVE", "PAST_DUE", "CANCELED")


def upgrade() -> None:
    values_sql = ", ".join(f"'{v}'" for v in _STATUS_VALUES)
    op.execute(
        f"DO $$ BEGIN "
        f"CREATE TYPE usersubscriptionstatus AS ENUM ({values_sql}); "
        f"EXCEPTION WHEN duplicate_object THEN NULL; "
        f"END $$;"
    )
    op.add_column("users", sa.Column(
        "subscription_status",
        sa.Enum(*_STATUS_VALUES, name="usersubscriptionstatus", create_type=False),
        server_default="NONE", nullable=False,
    ))
    op.add_column("users", sa.Column("auto_renew", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("users", sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("recurring_token", sa.String(length=50), nullable=True))
    op.add_column("users", sa.Column("subscription_amount", sa.Float(), nullable=True))
    op.add_column("users", sa.Column("card_last4", sa.String(length=4), nullable=True))

    op.alter_column("payments", "salon_id", nullable=True)
    op.add_column("payments", sa.Column(
        "user_id", sa.Integer(),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    ))
    op.create_index("ix_payments_user_id", "payments", ["user_id"])
    op.create_check_constraint(
        "check_payment_exactly_one_target", "payments",
        "(salon_id IS NOT NULL)::int + (user_id IS NOT NULL)::int = 1",
    )


def downgrade() -> None:
    op.drop_constraint("check_payment_exactly_one_target", "payments", type_="check")
    op.drop_index("ix_payments_user_id", table_name="payments")
    op.drop_column("payments", "user_id")
    op.alter_column("payments", "salon_id", nullable=False)

    op.drop_column("users", "card_last4")
    op.drop_column("users", "subscription_amount")
    op.drop_column("users", "recurring_token")
    op.drop_column("users", "trial_ends_at")
    op.drop_column("users", "auto_renew")
    op.drop_column("users", "subscription_status")
    op.execute("DROP TYPE IF EXISTS usersubscriptionstatus")
