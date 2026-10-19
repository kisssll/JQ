"""Обращения в поддержку: из какого сообщества ВКонтакте пришло

Revision ID: 7c3a91e5d2b8
Revises: d0e1f2a3b4c5

Ответ на обращение надо отправить тем токеном, которому человек написал
(решение 0013). До открытия поддержки в клиентском сообществе обращения из ВК
принимал только бизнесовый бот — поэтому все существующие строки с каналом VK
становятся бизнесовыми.
"""
import sqlalchemy as sa
from alembic import op

revision = "7c3a91e5d2b8"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("support_requests", sa.Column("vk_audience", sa.String(16), nullable=True))
    op.execute("UPDATE support_requests SET vk_audience = 'business' WHERE channel = 'VK'")


def downgrade() -> None:
    op.drop_column("support_requests", "vk_audience")
