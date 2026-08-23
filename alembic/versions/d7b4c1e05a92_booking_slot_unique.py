"""prevent double booking of the same slot (partial unique index)

Revision ID: d7b4c1e05a92
Revises: c5e91a3f7b28
Create Date: 2026-08-23

Проверка занятости слота и вставка записи не атомарны: при одновременных
запросах обе проходили проверку и обе создавали бронь (QA воспроизвёл — 2 из 10
параллельных гостевых запросов записались на один слот мастера). Ставим
частичный уникальный индекс на (master_id, start_time) для статусов, которые
реально занимают слот (PENDING/CONFIRMED — те же, что учитывает
BookingService.is_slot_available). Отменённые и неявки слот освобождают,
поэтому в индекс не входят и не мешают записаться заново.

Дубли, если они уже есть в базе, снимаем перед созданием индекса: оставляем
самую раннюю бронь на слот, остальные отменяем (данные не теряются — статус
CANCELLED, история цела).
"""
from alembic import op
import sqlalchemy as sa

revision = "d7b4c1e05a92"
down_revision = "c5e91a3f7b28"
branch_labels = None
depends_on = None

_INDEX = "uq_booking_master_slot_active"


def upgrade() -> None:
    # 1) расчистить существующие дубли (оставить самую раннюю)
    op.execute(
        """
        UPDATE bookings SET status = 'CANCELLED'
        WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY master_id, start_time ORDER BY id
                ) AS rn
                FROM bookings
                WHERE status IN ('PENDING', 'CONFIRMED')
            ) t WHERE t.rn > 1
        )
        """
    )
    # 2) запретить впредь
    op.execute(
        f"CREATE UNIQUE INDEX {_INDEX} ON bookings (master_id, start_time) "
        "WHERE status IN ('PENDING', 'CONFIRMED')"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
