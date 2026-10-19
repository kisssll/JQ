"""ВКонтакте: два сообщества — клиентское и бизнесовое

Revision ID: d0e1f2a3b4c5
Revises: 6aab9576f0fa

Старое сообщество становится бизнесовым (решение 0013, п. 4), поэтому прежний
адрес и его отметка отказа не копируются, а ПЕРЕИМЕНОВЫВАЮТСЯ: строки на месте,
ни одна привязка не теряется и не может разойтись с отметкой. Клиентский адрес
появляется пустым — его даст сам человек, написав новому сообществу.
"""
import sqlalchemy as sa
from alembic import op

revision = "d0e1f2a3b4c5"
down_revision = "6aab9576f0fa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("users", "vk_peer_id", new_column_name="vk_business_peer_id")
    op.alter_column("users", "vk_broken_at", new_column_name="vk_business_broken_at")
    op.execute("ALTER INDEX ix_users_vk_peer_id RENAME TO ix_users_vk_business_peer_id")

    op.add_column("users", sa.Column("vk_client_peer_id", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("vk_client_broken_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_users_vk_client_peer_id", "users", ["vk_client_peer_id"])


def downgrade() -> None:
    # Клиентские адреса при откате пропадают сознательно: прежний код шлёт
    # только старым (бизнесовым) токеном, и клиентский адрес в vk_peer_id дал
    # бы отказ ВК и ложную отметку «канал сломан».
    op.drop_index("ix_users_vk_client_peer_id", table_name="users")
    op.drop_column("users", "vk_client_broken_at")
    op.drop_column("users", "vk_client_peer_id")

    op.execute("ALTER INDEX ix_users_vk_business_peer_id RENAME TO ix_users_vk_peer_id")
    op.alter_column("users", "vk_business_broken_at", new_column_name="vk_broken_at")
    op.alter_column("users", "vk_business_peer_id", new_column_name="vk_peer_id")
