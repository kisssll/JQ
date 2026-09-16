"""ВКонтакте как канал уведомлений: бот сообщества

Revision ID: c3d4e5f6a7b9
Revises: b2c3d4e5f6a8
"""
import sqlalchemy as sa
from alembic import op

revision = "c3d4e5f6a7b9"
down_revision = "b2c3d4e5f6a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Новое значение enum нельзя использовать в той же транзакции, где оно
    # добавлено, — выносим в autocommit-блок (как ADS_EVENING_DEALS).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE notifychannel ADD VALUE IF NOT EXISTS 'VK'")

    op.add_column("users", sa.Column("vk_user_id", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("vk_peer_id", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("vk_name", sa.String(length=200), nullable=True))
    op.add_column("users", sa.Column("vk_broken_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_users_vk_user_id", "users", ["vk_user_id"])
    op.create_index("ix_users_vk_peer_id", "users", ["vk_peer_id"])


def downgrade() -> None:
    # Значение 'VK' из enum Postgres удалить не умеет — остаётся неиспользуемым.
    # Каналы, указывавшие на ВК, возвращаем в «нет»: иначе строки ссылались бы
    # на канал без адреса.
    op.execute("UPDATE users SET notify_channel = 'NONE' WHERE notify_channel = 'VK'")
    op.drop_index("ix_users_vk_peer_id", table_name="users")
    op.drop_index("ix_users_vk_user_id", table_name="users")
    op.drop_column("users", "vk_broken_at")
    op.drop_column("users", "vk_name")
    op.drop_column("users", "vk_peer_id")
    op.drop_column("users", "vk_user_id")
