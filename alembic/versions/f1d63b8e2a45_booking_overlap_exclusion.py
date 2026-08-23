"""atomic protection against overlapping bookings (EXCLUDE gist)

Revision ID: f1d63b8e2a45
Revises: e8a2f0d4c317
Create Date: 2026-08-24

Уникальный индекс из d7b4c1e05a92 ловил только СОВПАДЕНИЕ времени начала:
брони 11:30–12:30 и 12:00–12:30 у одного мастера он пропускал, хотя они
пересекаются. Ставим полноценное ограничение исключения по диапазону —
теперь пересечение любых видов невозможно на уровне БД, а не только «повезло
с проверкой».

btree_gist нужен, чтобы в одном GiST-индексе жили и равенство по master_id, и
пересечение диапазонов. На managed-БД расширение создаётся (проверено там же,
где pg_trgm); если привилегии нет — миграция не падает, а оставляет прежний
уникальный индекс как частичную защиту (см. DO-блок).

Существующие пересечения снимаем перед созданием: оставляем более раннюю
бронь, поздние отменяем (данные целы, статус CANCELLED).
"""
from alembic import op
import sqlalchemy as sa

revision = "f1d63b8e2a45"
down_revision = "e8a2f0d4c317"
branch_labels = None
depends_on = None

_ACTIVE = "status IN ('PENDING', 'CONFIRMED')"
_CONSTRAINT = "excl_booking_master_overlap"
_OLD_INDEX = "uq_booking_master_slot_active"


def upgrade() -> None:
    # 1) расчистить пересечения (оставляем более раннюю бронь)
    op.execute(
        f"""
        UPDATE bookings SET status = 'CANCELLED'
        WHERE id IN (
            SELECT b2.id FROM bookings b1
            JOIN bookings b2
              ON b2.master_id = b1.master_id
             AND b2.id > b1.id
             AND b2.start_time < b1.end_time
             AND b2.end_time > b1.start_time
            WHERE b1.{_ACTIVE} AND b2.{_ACTIVE}
        )
        """
    )
    # 2) ограничение исключения; без btree_gist оставляем прежний индекс
    op.execute(
        f"""
        DO $$
        BEGIN
            CREATE EXTENSION IF NOT EXISTS btree_gist;
            ALTER TABLE bookings ADD CONSTRAINT {_CONSTRAINT}
                EXCLUDE USING gist (
                    master_id WITH =,
                    tsrange(start_time, end_time) WITH &&
                ) WHERE ({_ACTIVE});
            DROP INDEX IF EXISTS {_OLD_INDEX};
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'btree_gist недоступен: остаётся уникальный индекс по времени начала';
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE bookings DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {_OLD_INDEX} ON bookings (master_id, start_time) "
        f"WHERE {_ACTIVE}"
    )
