"""Отметка «мессенджер отказал в доставке насовсем»

Раньше постоянный отказ Telegram (бот заблокирован, чат не найден) уходил в
журнал и забывался: канал оставался Telegram, и человек молча переставал
получать напоминания. Теперь такой канал помечается, доставка идёт запасным
каналом, а привязка сохраняется — разблокировал бота, и всё вернулось.

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f7
"""
import sqlalchemy as sa
from alembic import op

revision = "b2c3d4e5f6a8"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("tg_broken_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("max_broken_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "max_broken_at")
    op.drop_column("users", "tg_broken_at")
