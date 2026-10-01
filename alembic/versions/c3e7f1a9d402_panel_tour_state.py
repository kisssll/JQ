"""Состояние тура по бизнес-панели: запуск, прохождение, текущий шаг.

Три поля у пользователя, а не у салона (решение 0008, п. 6): тур объясняет
панель, а не конкретный салон, — у владельца двух салонов он один.

Разделение «запустили» и «прошли» нужно, чтобы потом судить о туре по доле
дошедших до конца, а не по доле увидевших полосу.

Шаг хранится КЛЮЧОМ, а не номером: состав шагов у каждого свой (он строится из
включённых разделов, см. app/services/panel_tour.py), и номер 7 завтра означал
бы другой шаг — стоило владельцу убрать раздел из панели. По ключу же мы либо
попадаем в тот самый шаг, либо честно видим, что его больше нет.

Миграция схемная: ни одной строки не меняет, все три поля пустые. Откат
снимает только их — у человека пропадает отметка о пройденном туре, и при
повторном upgrade тур запустится заново.

Revision ID: c3e7f1a9d402
Revises: b7d1c4e93a25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3e7f1a9d402"
down_revision: Union[str, None] = "b7d1c4e93a25"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("panel_tour_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("panel_tour_done_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("panel_tour_step", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "panel_tour_step")
    op.drop_column("users", "panel_tour_done_at")
    op.drop_column("users", "panel_tour_started_at")
