"""add email to salons

Revision ID: f7a1b2c3d4e5
Revises: c4d5e6f7a8b9
Create Date: 2026-07-27

Контактная почта салона (nullable): реквизиты новых сотрудников + копии
уведомлений о записях/отменах.
"""
from alembic import op
import sqlalchemy as sa

revision = "f7a1b2c3d4e5"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("salons", sa.Column("email", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("salons", "email")
