"""payments.receipt_status — судьба кассового чека (54-ФЗ)

Revision ID: b2c7e4f9a015
Revises: f1d63b8e2a45
Create Date: 2026-08-25

Чек пробивает касса по блоку Receipt из Init. Если он не пробился, оплата
всё равно прошла — нарушение тихое, поэтому статус надо где-то хранить,
чтобы по нему поднять алерт и потом найти проблемные платежи.
"""
import sqlalchemy as sa
from alembic import op

revision = "b2c7e4f9a015"
down_revision = "f1d63b8e2a45"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("receipt_status", sa.String(length=20),
                  server_default="none", nullable=False),
    )
    # Старые платежи фискализации не знали — так и помечаем, чтобы они не
    # попадали в выборку «чек не пробит».
    op.execute("UPDATE payments SET receipt_status = 'none'")


def downgrade() -> None:
    op.drop_column("payments", "receipt_status")
