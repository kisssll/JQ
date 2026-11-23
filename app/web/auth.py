# app/web/auth.py
from fastapi import Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, exists
from app.db.session import get_db
from app.models.models import User, SalonMember, Master
from app.models.sport import SportCoach, SportGymMember
from app.services.web_session import session_claims


async def get_current_user_from_cookie(request: Request, db: AsyncSession = Depends(get_db)):
    """Получает текущего пользователя из JWT-токена в куках."""
    token = request.cookies.get("access_token")
    if not token:
        return None
    payload = await session_claims(token)
    if payload is None:
        return None
    user_id = payload.get("sub")
    if user_id is None:
        return None

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    # Деактивированный аккаунт (мягкое удаление / блокировка) не аутентифицируем —
    # cookie мог остаться на другом устройстве (ср. deps.get_current_user).
    if user is not None and not user.is_active:
        return None
    if user is not None:
        # role="business" не всегда синхронизирован с реальным членством в
        # SalonMember (напр. салон подключён владельцу иным путём, без
        # обновления роли) — сайдбару нужен фактический признак доступа
        # к панели бизнеса, а не только устаревшее поле role.
        has_salon = await db.execute(
            select(
                exists().where(
                    SalonMember.user_id == user.id,
                    SalonMember.is_active == True,
                )
            )
        )
        user.has_salon_access = bool(has_salon.scalar())

        # Аналогично — role="master" не всегда синхронизирован с реальной
        # записью в Master (см. has_salon_access выше).
        has_master = await db.execute(
            select(exists().where(Master.user_id == user.id, Master.is_active == True))
        )
        user.has_master_profile = bool(has_master.scalar())

        has_sport = await db.execute(
            select(exists().where(
                SportGymMember.user_id == user.id,
                SportGymMember.is_active == True,
            ))
        )
        has_sport_coach = await db.execute(
            select(
                exists().where(
                    SportCoach.user_id == user.id,
                    SportCoach.is_active == True,
                )
            )
        )
        user.has_sport_access = bool(has_sport.scalar() or has_sport_coach.scalar())
    return user
