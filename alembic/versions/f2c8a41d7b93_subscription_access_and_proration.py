"""access_until, trial_used_at, proration watermark for subscriptions

Revision ID: f2c8a41d7b93
Revises: d4a71e9b6c02
Create Date: 2026-08-22

Тариф начинает реально влиять на доступ. Добавляем:

salons: access_until (докуда салон виден в ленте и принимает новую запись),
trial_used_at (триал один раз), billed_masters + pending_proration (планка
оплаченного штата и накопленная доплата за его рост), last_downgrade_at
(понижение раз в 3 месяца).

users (тарифы моделей): access_until, trial_used_at, last_downgrade_at —
без планки/доплаты: у модели нет штата, тарифы фиксированные.

Бэкфилл access_until:
  * триал (trialing) → trial_ends_at + 7 дней (запас для новых);
  * платившие/остальные с известным сроком → subscription_expires_at;
  * без подписки (none) → NULL, доступ закрыт.
Правила применяем сразу, без переходного периода — в базе только тестовые
салоны (решение Артёма).

billed_masters бэкфиллим фактическим числом активных мастеров: иначе первый
же пересчёт начислил бы доплату за уже работающих людей.
"""
from alembic import op
import sqlalchemy as sa

revision = "f2c8a41d7b93"
down_revision = "d4a71e9b6c02"
branch_labels = None
depends_on = None

GRACE_DAYS = 7


def upgrade() -> None:
    op.add_column("salons", sa.Column("access_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("salons", sa.Column("trial_used_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("salons", sa.Column("billed_masters", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("salons", sa.Column("pending_proration", sa.Float(), nullable=False, server_default="0"))
    op.add_column("salons", sa.Column("last_downgrade_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("users", sa.Column("access_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("trial_used_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("last_downgrade_at", sa.DateTime(timezone=True), nullable=True))

    for table in ("salons", "users"):
        # Триал — со запасом; всё прочее с известным сроком — ровно по нему.
        op.execute(
            f"UPDATE {table} SET access_until = trial_ends_at + interval '{GRACE_DAYS} days' "
            "WHERE subscription_status = 'TRIALING' AND trial_ends_at IS NOT NULL"
        )
        op.execute(
            f"UPDATE {table} SET access_until = subscription_expires_at "
            "WHERE access_until IS NULL AND subscription_status <> 'NONE' "
            "AND subscription_expires_at IS NOT NULL"
        )
        # Триал уже выдавали — отмечаем, чтобы второй раз не дали.
        op.execute(
            f"UPDATE {table} SET trial_used_at = trial_ends_at WHERE trial_ends_at IS NOT NULL"
        )

    # Планка = текущий активный штат (иначе доплата начислилась бы за уже
    # работающих мастеров при первом же пересчёте).
    op.execute(
        "UPDATE salons s SET billed_masters = COALESCE(("
        "  SELECT count(*) FROM masters m WHERE m.salon_id = s.id AND m.is_active = true"
        "), 0)"
    )


def downgrade() -> None:
    for column in ("access_until", "trial_used_at", "billed_masters",
                   "pending_proration", "last_downgrade_at"):
        op.drop_column("salons", column)
    for column in ("access_until", "trial_used_at", "last_downgrade_at"):
        op.drop_column("users", column)
