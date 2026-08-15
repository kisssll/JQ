"""add city to salons

Revision ID: a3b4c5d6e7f8
Revises: f7a1b2c3d4e5
Create Date: 2026-08-02

Отдельное поле города (из фиксированного списка app/web/cities.py) — нужно
для фильтра по городу и «умного» списка категорий на /salons, чтобы не
парсить город из свободной строки address. Существующие салоны бэкфилятся
в Новосибирск — сейчас платформа запущена только там.
"""
from alembic import op
import sqlalchemy as sa

revision = "a3b4c5d6e7f8"
down_revision = "f7a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("salons", sa.Column("city", sa.String(length=100), nullable=False, server_default=""))
    op.execute("UPDATE salons SET city = 'Новосибирск' WHERE city = ''")


def downgrade() -> None:
    op.drop_column("salons", "city")
