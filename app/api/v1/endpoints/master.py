# app/api/v1/endpoints/master.py
from typing import Optional
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Request, Form, status
from fastapi.responses import RedirectResponse, HTMLResponse
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
    """Добавление мастера владельцем/админом салона через веб-форму."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    resolved_id = await get_user_primary_salon_id(db, user.id, salon_id)
    if resolved_id is None:
        return RedirectResponse(url="/business/register-salon", status_code=302)
    try:
        await check_salon_permission(db, user, resolved_id, "manage_masters")
    except HTTPException:
        return HTMLResponse(content="Недостаточно прав для управления мастерами", status_code=403)
    salon = (await db.execute(select(Salon).where(Salon.id == resolved_id))).scalar_one_or_none()
    if salon is None:
        return HTMLResponse(content="Салон не найден", status_code=404)

    # Телефон из формы может быть в любом виде ("+7 (948) 758-97-34" и т.п.) —
    # нормализуем к +7XXXXXXXXXX, иначе не влезет в users.phone (String(15))
    # и не совпадёт при поиске с уже зарегистрированным пользователем.
    norm_phone = try_normalize_phone(phone)
    if norm_phone is None:
        return RedirectResponse(url="/business/my-salon?error=bad_phone", status_code=302)

    # Проверяем, нет ли уже мастера с таким телефоном
    temp_password = None
    existing_user = (await db.execute(select(User).where(User.phone == norm_phone))).scalar_one_or_none()
    if existing_user:
        # Если пользователь уже есть, просто создаём профиль мастера
        existing_master = (await db.execute(select(Master).where(Master.user_id == existing_user.id))).scalar_one_or_none()
        if existing_master:
            return RedirectResponse(url="/business/my-salon?error=master_exists", status_code=302)
        master_user = existing_user
    else:
        # Уникальный случайный временный пароль (не общий "master123").
        # Показываем владельцу один раз; мастер обязан сменить его при входе.
        temp_password = secrets.token_urlsafe(9)
        master_user = User(
            phone=norm_phone,
            full_name=full_name,
            hashed_password=get_password_hash(temp_password),
            role=UserRole.MASTER,
            is_active=True
        )
        db.add(master_user)
        await db.flush()
    
    # Создаём профиль мастера
    master = Master(
        user_id=master_user.id,
        salon_id=salon.id,
        specialization=specialization,
        experience_years=experience_years,
        rating=0.0
    )
    db.add(master)
    await db.commit()

    # Показываем временный пароль владельцу один раз (для передачи мастеру)
    if temp_password:
        return RedirectResponse(
            url=f"/business/my-salon?added=1&temp_pw={quote(temp_password)}",
            status_code=302,
        )
    return RedirectResponse(url="/business/my-salon?added=1", status_code=302)


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

    return RedirectResponse(url="/business/dashboard?tab=employees", status_code=302)