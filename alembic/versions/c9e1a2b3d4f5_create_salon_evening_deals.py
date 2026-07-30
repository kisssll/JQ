"""create salon_evening_deals

Revision ID: c9e1a2b3d4f5
Revises: f7a1b2c3d4e5
Create Date: 2026-07-30

«Вечерние окна со скидкой» салона (1:1). Пустые вечерние слоты на сегодня
попадают в подборку /evening-deals; ежедневная ТГ-рассылка зовёт занять.
Новая таблица, бэкфилл не нужен (по умолчанию участие выключено — строки нет).
"""
from alembic import op
import sqlalchemy as sa

revision = "c9e1a2b3d4f5"
down_revision = "f7a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "salon_evening_deals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "salon_id", sa.Integer(),
            sa.ForeignKey("salons.id", ondelete="CASCADE"),
            nullable=False, unique=True,
        ),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("discount_percent", sa.Integer(), server_default="0", nullable=False),
        sa.Column("evening_from", sa.Time(), nullable=False),
        sa.Column("evening_to", sa.Time(), nullable=False),
        sa.Column("weekdays", sa.JSON(), nullable=True),
        sa.Column("service_ids", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_salon_evening_deals_salon_id", "salon_evening_deals", ["salon_id"])


def downgrade() -> None:
    op.drop_index("ix_salon_evening_deals_salon_id", table_name="salon_evening_deals")
    op.drop_table("salon_evening_deals")
