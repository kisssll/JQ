"""Режим бизнес-панели салона: solo/team + список включённых разделов.

Существующие салоны разводим по факту: 1 активный мастер или меньше — «работаю
один», больше — «у меня команда» (тот же порог, что в
app/services/panel_sections.mode_for_master_count).

Карточку мастера салонам без мастера НЕ заводим (решение владельца 03.10.2026).
Раньше здесь был INSERT на создателя салона: без карточки к человеку нельзя
записаться, и в эту дыру провалился один салон на проде. Теперь дыру показывает
сама панель — блок «Можно ли к вам записаться» в «Обзоре» (заход 2) и тур
(заход 3), а кнопка «Создать мою карточку мастера» стоит прямо в разделе.
Миграция не должна заводить людям сущности, которых они не просили, тем более
необратимо (downgrade такую вставку не убирал) и с угаданной специализацией.

Revision ID: b7d1c4e93a25
Revises: a7b8c9d0e1f2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7d1c4e93a25"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    panel_mode = sa.Enum("SOLO", "TEAM", name="salonpanelmode")
    panel_mode.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "salons",
        sa.Column(
            "panel_mode", panel_mode,
            nullable=False, server_default="SOLO",
        ),
    )
    op.add_column("salons", sa.Column("panel_sections", sa.JSON(), nullable=True))

    # Порог: больше одного активного мастера — значит команда. Считаем только
    # активных: отключённый мастер не работает, платить и показывать разделы
    # штата из-за него незачем.
    op.execute(
        """
        UPDATE salons AS s
           SET panel_mode = 'TEAM'
         WHERE (
                 SELECT count(*) FROM masters AS m
                  WHERE m.salon_id = s.id AND m.is_active = true
               ) > 1
        """
    )


def downgrade() -> None:
    # Откат снимает режим и набор разделов, панель возвращается к «16 вкладок
    # всем одинаково». Данных миграция не меняет, так что терять нечего.
    op.drop_column("salons", "panel_sections")
    op.drop_column("salons", "panel_mode")
    sa.Enum(name="salonpanelmode").drop(op.get_bind(), checkfirst=True)
