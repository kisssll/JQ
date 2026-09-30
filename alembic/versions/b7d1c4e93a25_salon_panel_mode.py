"""Режим бизнес-панели салона: solo/team + список включённых разделов.

Существующие салоны разводим по факту: 1 активный мастер или меньше — «работаю
один», больше — «у меня команда» (тот же порог, что в
app/services/panel_sections.mode_for_master_count). Салонам, где мастера нет
вообще, заводим карточку мастера на создателя: без неё к человеку нельзя
записаться, и именно в эту дыру провалился один салон на проде.

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

    # Салон без мастера вообще: заводим карточку на создателя салона.
    # Специализацию ставим нейтральную: владелец допишет в панели.
    #
    # masters.user_id УНИКАЛЕН, и это накладывает два ограничения сразу:
    #   1) пропускаем тех, у кого карточка мастера уже есть (пусть даже в чужом
    #      салоне) — иначе вставка упала бы на уникальном индексе;
    #   2) DISTINCT ON (creator_id): один человек может владеть несколькими
    #      салонами, и если без мастера остались ДВА его салона, обычный SELECT
    #      вернул бы две строки с одним user_id — NOT EXISTS их не отсечёт, он
    #      считается до вставки. Берём салон с наименьшим id (самый старый).
    op.execute(
        """
        INSERT INTO masters (user_id, salon_id, specialization, experience_years,
                             rating, break_minutes, is_active, seeking_models)
        SELECT DISTINCT ON (s.creator_id)
               s.creator_id, s.id, 'Мастер', 0, 0.0, 15, true, false
          FROM salons AS s
         WHERE s.creator_id IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM masters AS m WHERE m.salon_id = s.id)
           AND NOT EXISTS (SELECT 1 FROM masters AS m WHERE m.user_id = s.creator_id)
         ORDER BY s.creator_id, s.id
        """
    )


def downgrade() -> None:
    # Данные не удаляем: карточки мастеров, заведённые при upgrade, остаются —
    # к этим людям уже могли записаться, и снос карточки убил бы записи.
    # Откат снимает только сам режим и набор разделов, панель возвращается к
    # «16 вкладок всем одинаково».
    op.drop_column("salons", "panel_sections")
    op.drop_column("salons", "panel_mode")
    sa.Enum(name="salonpanelmode").drop(op.get_bind(), checkfirst=True)
