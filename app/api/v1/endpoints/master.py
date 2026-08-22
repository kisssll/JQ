# app/api/v1/endpoints/master.py
from typing import Optional
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Request, Form, status
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
import secrets

from app.db.session import get_db
from app.models.models import User, Master, Booking, Salon, UserRole, BookingStatus, Review, ReviewTargetType
from app.api.deps import (
    get_current_user, require_role, check_salon_permission, get_user_primary_salon_id,
)
from app.core.security import get_password_hash
from app.schemas.user import try_normalize_phone

router = APIRouter()

@router.get("/schedule")
async def get_my_schedule(
    current_user: User = Depends(require_role(UserRole.MASTER)),
    db: AsyncSession = Depends(get_db)
):
    """Получить своё расписание (только для MASTER)"""
    
    result = await db.execute(
        select(Master).where(Master.user_id == current_user.id)
    )
    master = result.scalar_one_or_none()
    
    if not master:
        raise HTTPException(status_code=404, detail="Профиль мастера не найден")
    
    bookings_result = await db.execute(
        select(Booking)
        .where(
            Booking.master_id == master.id,
            Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED])
        )
        .order_by(Booking.start_time)
    )
    bookings = bookings_result.scalars().all()
    
    return {
        "master_id": master.id,
        "specialization": master.specialization,
        "bookings": [
            {
                "id": b.id,
                "start_time": b.start_time.isoformat(),
                "end_time": b.end_time.isoformat(),
                "status": b.status.value,
                "client_name": f"Клиент #{b.client_id}"
            }
            for b in bookings
        ]
    }


async def _sync_billing_headcount(db, salon_id: int) -> None:
    """Пересчитать «планку» оплаченного штата салона после изменений в составе.

    Штат вырос сверх оплаченного — начисляем доплату за остаток месяца (она
    попадёт в следующий счёт, сейчас денег не берём). Сокращение штата планку
    не опускает: возвратов нет, а повторное включение того же мастера не
    должно начислять второй раз (см. services/subscription.register_headcount).
    """
    from sqlalchemy import func as _func
    from app.models.models import Salon as _Salon
    from app.services.subscription import register_headcount

    salon = await db.get(_Salon, salon_id)
    if salon is None:
        return
    active = (await db.execute(
        select(_func.count(Master.id)).where(
            Master.salon_id == salon_id, Master.is_active == True,  # noqa: E712
        )
    )).scalar() or 0
    register_headcount(salon, active)
    await db.commit()


@router.post("/create-web")
async def create_master_web(
    request: Request,
    full_name: str = Form(...),
    phone: str = Form(...),
    specialization: str = Form(...),
    experience_years: int = Form(0),
    salon_id: Optional[int] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """Добавление мастера владельцем/админом. Возвращает JSON; при создании
    НОВОГО аккаунта — реквизиты для попапа (пароль не уходит в URL)."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return JSONResponse({"status": "error", "detail": "Требуется вход"}, status_code=401)

    resolved_id = await get_user_primary_salon_id(db, user.id, salon_id)
    if resolved_id is None:
        return JSONResponse({"status": "error", "detail": "Салон не найден"}, status_code=404)
    try:
        await check_salon_permission(db, user, resolved_id, "manage_masters")
    except HTTPException:
        return JSONResponse({"status": "error", "detail": "Недостаточно прав для управления мастерами"}, status_code=403)
    salon = (await db.execute(select(Salon).where(Salon.id == resolved_id))).scalar_one_or_none()
    if salon is None:
        return JSONResponse({"status": "error", "detail": "Салон не найден"}, status_code=404)

    # Телефон нормализуем к +7XXXXXXXXXX — это же логин мастера.
    norm_phone = try_normalize_phone(phone)
    if norm_phone is None:
        return JSONResponse({"status": "error", "detail": "Некорректный номер телефона"}, status_code=400)

    temp_password = None
    existing_user = (await db.execute(select(User).where(User.phone == norm_phone))).scalar_one_or_none()
    if existing_user:
        existing_master = (await db.execute(select(Master).where(Master.user_id == existing_user.id))).scalar_one_or_none()
        if existing_master:
            return JSONResponse({"status": "error", "detail": "Мастер с таким телефоном уже добавлен"}, status_code=400)
        master_user = existing_user
    else:
        # Уникальный временный пароль — показываем в попапе один раз.
        temp_password = secrets.token_urlsafe(9)
        master_user = User(
            phone=norm_phone, full_name=full_name,
            hashed_password=get_password_hash(temp_password),
            role=UserRole.MASTER, is_active=True,
        )
        db.add(master_user)
        await db.flush()

    master = Master(
        user_id=master_user.id, salon_id=salon.id,
        specialization=specialization, experience_years=experience_years, rating=0.0,
    )
    db.add(master)
    await db.commit()
    await _sync_billing_headcount(db, salon.id)

    # Реквизиты возвращаем только для НОВОГО аккаунта (у существующего — свой пароль).
    creds = None
    if temp_password:
        creds = {"name": full_name, "login": norm_phone, "password": temp_password}
    return JSONResponse({"status": "ok", "credentials": creds})


@router.post("/{master_id}/reset-password")
async def reset_master_password(
    master_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Сброс пароля мастера: генерит новый временный пароль и возвращает
    реквизиты для попапа (на случай «упустил окно» / забытого пароля)."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return JSONResponse({"status": "error", "detail": "Требуется вход"}, status_code=401)

    master = (await db.execute(select(Master).where(Master.id == master_id))).scalar_one_or_none()
    if master is None:
        return JSONResponse({"status": "error", "detail": "Мастер не найден"}, status_code=404)
    try:
        await check_salon_permission(db, user, master.salon_id, "manage_masters")
    except HTTPException:
        return JSONResponse({"status": "error", "detail": "Недостаточно прав"}, status_code=403)

    master_user = (await db.execute(select(User).where(User.id == master.user_id))).scalar_one_or_none()
    if master_user is None:
        return JSONResponse({"status": "error", "detail": "Аккаунт мастера не найден"}, status_code=404)
    salon = (await db.execute(select(Salon).where(Salon.id == master.salon_id))).scalar_one_or_none()
    if salon is not None and salon.creator_id == master_user.id:
        return JSONResponse({"status": "error", "detail": "Нельзя сбросить пароль создателя салона"}, status_code=400)

    new_password = secrets.token_urlsafe(9)
    master_user.hashed_password = get_password_hash(new_password)
    await db.commit()
    return JSONResponse({"status": "ok", "credentials": {
        "name": master_user.full_name, "login": master_user.phone, "password": new_password,
    }})


@router.post("/{master_id}/update")
async def update_master_web(
    master_id: int,
    request: Request,
    full_name: str = Form(...),
    specialization: str = Form(...),
    experience_years: int = Form(0),
    db: AsyncSession = Depends(get_db)
):
    """Обновление данных мастера владельцем/админом салона."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    master = (await db.execute(select(Master).where(Master.id == master_id))).scalar_one_or_none()
    if not master:
        return HTMLResponse(content="Мастер не найден", status_code=404)

    try:
        await check_salon_permission(db, user, master.salon_id, "manage_masters")
    except HTTPException:
        return HTMLResponse(content="Недостаточно прав для управления мастерами", status_code=403)
    
    # Обновляем имя пользователя
    master_user = (await db.execute(select(User).where(User.id == master.user_id))).scalar_one_or_none()
    if master_user:
        master_user.full_name = full_name
    
    # Обновляем данные мастера
    master.specialization = specialization
    master.experience_years = experience_years
    await db.commit()
    
    return RedirectResponse(url="/business/my-salon?updated=1", status_code=302)


@router.post("/{master_id}/delete")
async def delete_master_web(
    master_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Удаление мастера владельцем/админом салона."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    master = (await db.execute(select(Master).where(Master.id == master_id))).scalar_one_or_none()
    if not master:
        return HTMLResponse(content="Мастер не найден", status_code=404)

    try:
        await check_salon_permission(db, user, master.salon_id, "manage_masters")
    except HTTPException:
        return HTMLResponse(content="Недостаточно прав для управления мастерами", status_code=403)

    # Мягкое удаление: мастер скрывается (is_active=False), но его услуги,
    # брони и отзывы (история записей клиентов) сохраняются. Hard-delete ронял
    # 500 (ORM обнулял services.master_id NOT NULL) и снёс бы историю клиентов.
    master.is_active = False
    await db.commit()

    return RedirectResponse(url="/business/my-salon?deleted=1", status_code=302)


@router.post("/{master_id}/toggle")
async def toggle_master_web(
    master_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Включение/отключение мастера."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    master = (await db.execute(select(Master).where(Master.id == master_id))).scalar_one_or_none()
    if not master:
        return HTMLResponse(content="Мастер не найден", status_code=404)

    try:
        await check_salon_permission(db, user, master.salon_id, "manage_masters")
    except HTTPException:
        return HTMLResponse(content="Недостаточно прав для управления мастерами", status_code=403)

    master.is_active = not master.is_active

    if not master.is_active:
        # Мастер ушёл из салона — отзывы «про него» остаются в общем списке
        # салона, но перестают быть привязаны к конкретному (уже неактивному)
        # мастеру. Фото в этих отзывах не трогаем — они относятся к отзыву,
        # не к мастеру напрямую.
        await db.execute(
            update(Review)
            .where(Review.master_id == master.id, Review.target_type == ReviewTargetType.MASTER)
            .values(master_id=None)
        )

    await db.commit()
    await _sync_billing_headcount(db, master.salon_id)

    return RedirectResponse(url="/business/dashboard?tab=employees", status_code=302)