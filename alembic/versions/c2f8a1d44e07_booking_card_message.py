"""booking card in a messenger

Revision ID: c2f8a1d44e07
Revises: b1c4e7f20a33
Create Date: 2026-11-14 11:00:00.000000

Живая карточка записи (решение 0021, п. 2). Карточка в переписке меняется на
месте, но запись меняется и мимо неё — отмена на сайте, отмена салоном,
перенос с другого устройства. Чтобы бот мог переписать карточку, у записи
хранится адрес сообщения: канал, чат и номер сообщения.

Номер строкой: у MAX он строковый (mid), у Telegram и ВК числовой — одна
колонка на три канала дешевле трёх типов.

Тип notifychannel уже существует (d4a71e9b6c02 + c3d4e5f6a7b9), поэтому
create_type=False: повторное создание уронило бы миграцию.

Автогенерация, как и в a765971adfd9 и b1c4e7f20a33, предлагает полсотни
посторонних правок (NOT NULL у created_at и т. п.) — это давний дрейф схемы,
к карточке он не относится, и они выкинуты намеренно: менять прод заодно
нельзя.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c2f8a1d44e07"
down_revision: Union[str, None] = "b1c4e7f20a33"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CHANNEL = postgresql.ENUM(name="notifychannel", create_type=False)


def upgrade() -> None:
    op.add_column("bookings", sa.Column("card_channel", _CHANNEL, nullable=True))
    op.add_column("bookings", sa.Column("card_chat_id", sa.BigInteger(), nullable=True))
    op.add_column("bookings", sa.Column("card_message_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("bookings", "card_message_id")
    op.drop_column("bookings", "card_chat_id")
    op.drop_column("bookings", "card_channel")
