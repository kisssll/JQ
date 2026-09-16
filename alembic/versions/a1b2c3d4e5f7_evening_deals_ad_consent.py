"""Согласие на рекламную рассылку вечерних окон

Revision ID: a1b2c3d4e5f7
Revises: f0a1b2c3d4e5
Create Date: 2026-09-16

Рассылка «вечерние окна со скидкой» — реклама, и по ч. 1 ст. 18 закона
«О рекламе» её можно слать только с предварительного согласия. До сих пор
тема работала по схеме «включено, пока не отписался» — это отсутствие
согласия, а не оно.

Два шага:
  1. новый тип документа в журнале согласий — чтобы согласие можно было
     доказать датой и способом;
  2. снять явное «включено» с тех, у кого оно стоит БЕЗ записи в журнале.
     До этой миграции записей такого типа не существовало, значит, ни одно
     такое «включено» согласием не подкреплено. На проде на 16.09.2026 таких
     людей ноль (14 потенциальных получателей настройку не трогали, а сама
     подборка не уходила — ни одна акция не была включена), но
     инвариант должен держаться на любой базе, а не только на этой.
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f7"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None

_TOPIC = "evening_deals"


def upgrade() -> None:
    # ADD VALUE нельзя использовать в той же транзакции, где значение
    # появилось, поэтому — отдельным автокоммит-блоком. Метка — ИМЯ члена
    # перечисления, как у остальных значений этого типа.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE consentdocument ADD VALUE IF NOT EXISTS 'ADS_EVENING_DEALS'")

    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, tg_notify_prefs FROM users WHERE tg_notify_prefs IS NOT NULL"
    )).fetchall()
    for user_id, prefs in rows:
        data = prefs if isinstance(prefs, dict) else json.loads(prefs or "{}")
        if data.get(_TOPIC) is True:
            data.pop(_TOPIC)
            bind.execute(
                sa.text("UPDATE users SET tg_notify_prefs = CAST(:p AS json) WHERE id = :id"),
                {"p": json.dumps(data), "id": user_id},
            )


def downgrade() -> None:
    # Удалить значение из enum в PostgreSQL нельзя без пересоздания типа, а
    # снятые «включено» восстанавливать нельзя по смыслу — это и было
    # нарушение. Откат схемы здесь не имеет безопасного варианта.
    pass
