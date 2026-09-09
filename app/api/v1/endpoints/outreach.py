# app/api/v1/endpoints/outreach.py
"""Сверка холодной базы аутрича с базой Руми — по хешам телефонов.

Зачем отдельным эндпоинтом. Инструмент аутрича (beauty-sec/lead-finder, слой
outreach) ведёт очередь мастеров, которых мы подключаем. Ему нужно знать, кто
из них уже дошёл до продукта: иначе сотрудник вручную сверяет две базы, а
статус «активен» проставляется на глаз — ровно та ловушка, от которой
предостерегает стратегия привлечения («не радуемся регистрациям без активации»).

Почему хеши, а не телефоны. Через границу едет минимум: сервер не узнаёт
телефонов тех, кого мы ещё только собираемся звать, а инструмент не получает
телефонов чужих пользователей. Соль общая и постоянная — при её смене сверка
просто перестанет находить совпадения, данные не пострадают.

Почему не прямой доступ к базе. Открывать боевой Postgres с персданными
клиентов наружу ради вспомогательного инструмента продаж — плохая сделка.
Здесь наружу торчит один метод под админской авторизацией, и вызовы попадают
в журнал аудита.
"""
from __future__ import annotations

import hashlib
import os
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.models import (
    Booking, Master, Salon, SalonMember, User,
)
from app.services.subscription import _now

router = APIRouter()

_SALT_ENV = "OUTREACH_HASH_SALT"

#: Окно, в котором запись считается признаком живого пользования. Взято из
#: определения «активного мастера» в стратегии: ≥1 реальная запись за 7 дней.
ACTIVE_WINDOW_DAYS = 7
#: Молчание дольше этого срока при наличии прошлых записей = отвалился.
CHURN_WINDOW_DAYS = 30

#: Больше за раз не принимаем: очередь аутрича — это сотни строк, а не тысячи,
#: и неограниченный список превратил бы метод в способ перебирать телефоны.
MAX_HASHES = 500


class MatchRequest(BaseModel):
    hashes: list[str] = Field(..., min_length=1, max_length=MAX_HASHES)


def _fingerprint(phone: str, salt: str) -> str:
    """Та же схема, что в outreach/retention.py: соль, двоеточие, значение."""
    normalized = phone.strip().lower().lstrip("@")
    return hashlib.sha256(f"{salt}:{normalized}".encode()).hexdigest()


async def _state_for(db: AsyncSession, user: User) -> str:
    """Что Руми знает про этого человека.

    Порядок важен: платящий интереснее активного, активный — просто
    зарегистрированного. В одну колонку помещается только один ответ, поэтому
    выбираем самый содержательный.
    """
    now = _now()

    salon_ids = set((await db.execute(
        select(SalonMember.salon_id).where(
            SalonMember.user_id == user.id, SalonMember.is_active.is_(True)
        )
    )).scalars().all())

    if salon_ids:
        paid = (await db.execute(
            select(Salon.id).where(
                Salon.id.in_(salon_ids),
                Salon.subscription_expires_at.isnot(None),
                Salon.subscription_expires_at > now,
            ).limit(1)
        )).scalar_one_or_none()
        if paid is not None:
            return "платит"

    # Записи считаем и по салонам человека, и по его мастер-профилю: соло-мастер
    # может быть заведён и так, и так.
    master_ids = set((await db.execute(
        select(Master.id).where(Master.user_id == user.id)
    )).scalars().all())
    if salon_ids:
        master_ids |= set((await db.execute(
            select(Master.id).where(Master.salon_id.in_(salon_ids))
        )).scalars().all())

    if not master_ids:
        return "зарегистрирован"

    last_booking = (await db.execute(
        select(Booking.created_at)
        .where(Booking.master_id.in_(master_ids))
        .order_by(Booking.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    if last_booking is None:
        return "зарегистрирован"
    if last_booking >= now - timedelta(days=ACTIVE_WINDOW_DAYS):
        return "активен"
    if last_booking < now - timedelta(days=CHURN_WINDOW_DAYS):
        return "отвалился"
    return "зарегистрирован"


@router.post("/match")
async def match_outreach(
    request: Request,
    data: MatchRequest,
    db: AsyncSession = Depends(get_db),
):
    """Хеши телефонов → состояние в Руми. Только для модераторов."""
    from app.api.v1.endpoints.admin import _get_admin

    admin = await _get_admin(request, db)
    if admin is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только для модераторов")

    salt = os.environ.get(_SALT_ENV, "").strip()
    if not salt:
        # Без соли метод посчитал бы хеши от «пустой» схемы и молча не нашёл
        # никого — хуже явной ошибки: сотрудник решил бы, что никто не дошёл.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{_SALT_ENV} не задан на сервере — сверка невозможна",
        )

    wanted = set(data.hashes)
    result = {h: "нет" for h in wanted}

    # Пользователей пока сотни: считаем хеши на лету, без отдельной колонки в
    # базе. Появятся десятки тысяч — здесь понадобится индекс, но не раньше:
    # хранить хеш телефона рядом с самим телефоном смысла не имеет.
    users = (await db.execute(
        select(User).where(User.is_guest.is_(False), User.is_active.is_(True))
    )).scalars().all()

    for user in users:
        if not user.phone:
            continue
        digest = _fingerprint(user.phone, salt)
        if digest in wanted:
            result[digest] = await _state_for(db, user)

    return result
