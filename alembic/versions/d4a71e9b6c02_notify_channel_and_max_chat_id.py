"""add notify_channel + max_chat_id to users

Revision ID: d4a71e9b6c02
Revises: 7431cb422184
Create Date: 2026-08-22

Канал уведомлений. Раньше доставка была только в Telegram (users.tg_chat_id),
а подтвердившийся через MAX не получал уведомлений вообще — его chat_id
нигде не сохранялся. Добавляем:

- users.max_chat_id — зеркало tg_chat_id для MAX;
- users.notify_channel — куда слать (none/tg/max/email).

Бэкфилл: у кого уже привязан Telegram — канал tg; у остальных, если есть
email — email (хоть какая-то доставка); иначе none (увидят мягкий промпт
«подключите канал уведомлений»).
"""
from alembic import op
import sqlalchemy as sa

revision = "d4a71e9b6c02"
down_revision = "7431cb422184"
branch_labels = None
depends_on = None

_CHANNELS = ("NONE", "TG", "MAX", "EMAIL")


def upgrade() -> None:
    notify_channel = sa.Enum(*_CHANNELS, name="notifychannel")
    notify_channel.create(op.get_bind(), checkfirst=True)

    op.add_column("users", sa.Column("max_chat_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_users_max_chat_id", "users", ["max_chat_id"])
    op.add_column(
        "users",
        sa.Column("notify_channel", notify_channel, nullable=False, server_default="NONE"),
    )

    # Бэкфилл: привязанный Telegram → tg, иначе почта → email, иначе none.
    op.execute("UPDATE users SET notify_channel = 'TG' WHERE tg_chat_id IS NOT NULL")
    op.execute(
        "UPDATE users SET notify_channel = 'EMAIL' "
        "WHERE tg_chat_id IS NULL AND email IS NOT NULL AND email <> ''"
    )


def downgrade() -> None:
    op.drop_index("ix_users_max_chat_id", table_name="users")
    op.drop_column("users", "max_chat_id")
    op.drop_column("users", "notify_channel")
    sa.Enum(name="notifychannel").drop(op.get_bind(), checkfirst=True)
