"""Кто считается клиентом салона.

Одно определение на всё, что салон делает с человеком как с клиентом: список
во вкладке «Клиенты», карточка клиента, заметки, ручная лояльность (статус
«постоянный», персональная скидка, баллы). Два разных определения разошлись
бы: салон видел бы в списке одних людей, а писать мог бы про других.

Клиент салона — человек, у которого есть ЗАВЕРШЁННАЯ запись (визит
состоялся) к любому мастеру этого салона. Именно так вкладка «Клиенты»
собирала список и до этого правила; гостевые записи сюда попадают на общих
основаниях — у гостя тоже заводится пользователь.

Зачем вообще проверка (решение 0017, п. 2): права проверялись на салон, а
связь человека с салоном — нет, и владелец мог завести заметку или баллы на
любого пользователя сервиса. Это обработка персональных данных человека,
который салону никто, и заодно оракул перебора чужих id.
"""
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Booking, BookingStatus, Master


def client_bookings_filter(salon_id: int):
    """Условие на Booking: запись этого салона, по которой человек — клиент."""
    return (
        Booking.master_id.in_(select(Master.id).where(Master.salon_id == salon_id)),
        Booking.status == BookingStatus.COMPLETED,
    )


async def is_salon_client(db: AsyncSession, salon_id: int, client_id: int) -> bool:
    return bool(await db.scalar(select(exists().where(
        Booking.client_id == client_id, *client_bookings_filter(salon_id),
    ))))
