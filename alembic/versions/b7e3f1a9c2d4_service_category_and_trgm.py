"""add Service.category + pg_trgm for salon search

Revision ID: b7e3f1a9c2d4
Revises: 3024a7a5be87
Create Date: 2026-08-17

Серверные фильтры/поиск на /salons. Три вещи:

1) services.category (nullable slug из service_categories) — категория услуги
   как хранимый факт, а не угадывание из названия. Гибрид: матчер подсказывает
   при создании, владелец переопределяет. Теги на карточке салона и фильтр по
   категории строятся по этой колонке.

2) Бэкфилл существующих услуг матчером (suggest_category по названию) — первый
   совпавший слаг; без совпадения категория остаётся NULL (владелец проставит
   вручную).

3) Расширение pg_trgm для устойчивого к опечаткам поиска (в связке с FTS
   russian, который встроен и расширения не требует). CREATE EXTENSION обёрнут
   в DO-блок, гасящий ошибку привилегии — на managed-БД без права создавать
   расширение миграция НЕ падает, а поиск в рантайме деградирует в FTS-only
   (см. app/web/pages/salons.py::_trgm_available).
"""
from alembic import op
import sqlalchemy as sa

revision = "b7e3f1a9c2d4"
down_revision = "3024a7a5be87"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) колонка
    op.add_column("services", sa.Column("category", sa.String(length=40), nullable=True))

    # 3) pg_trgm — не роняем миграцию, если нет привилегии (managed-БД)
    # NB: без символов '%' в SQL — SQLAlchemy принимает их за маркер параметра.
    op.execute(
        """
        DO $$
        BEGIN
            CREATE EXTENSION IF NOT EXISTS pg_trgm;
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'pg_trgm недоступен: поиск деградирует в FTS-only';
        END
        $$;
        """
    )

    # 2) бэкфилл матчером — тем же кодом, что подсказывает категорию в форме
    from app.web.service_categories import suggest_category

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, name FROM services")).fetchall()
    for sid, name in rows:
        slug = suggest_category(name or "")
        if slug:
            conn.execute(
                sa.text("UPDATE services SET category = :c WHERE id = :i"),
                {"c": slug, "i": sid},
            )


def downgrade() -> None:
    op.drop_column("services", "category")
    # pg_trgm намеренно не сносим: расширение общее, другие фичи могут на него
    # опереться, а DROP EXTENSION каскадит по зависимостям.
