# app/api/v1/endpoints/business.py
from datetime import date
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Form, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List
from fastapi.responses import HTMLResponse

from app.db.session import get_db
from app.models.models import (
    User, Salon, SalonPhoto, Master, Service, Promotion,
    SalonMember, SalonRole, OWNER_DEFAULT_PERMISSIONS, AdminAudit, ClientNote,
    SalonModel, UserRole, SalonModerationStatus,
)
from app.schemas.business import (
    SalonUpdateRequest,
    SalonResponse,
    MasterResponse,
    ServiceResponse,
    PromotionResponse
)
from app.api.deps import (
    get_current_user, check_salon_permission, get_user_primary_salon_id, get_salon_membership,
)
from app.services.analytics_service import AnalyticsService
from app.core.config import settings


def _validate_coords(latitude: Optional[float], longitude: Optional[float]) -> bool:
    """True, если координаты присутствуют и в разумных пределах."""
    return (
        latitude is not None and longitude is not None
        and -90 <= latitude <= 90 and -180 <= longitude <= 180
    )

router = APIRouter()


async def get_current_salon(
    salon_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Salon:
    """
    Резолвит салон, к которому у текущего пользователя есть активное членство
    (owner или admin). Без salon_id — берётся салон, где он создатель, иначе
    первый по дате. Не проверяет конкретное право — только сам факт членства;
    эндпоинты, требующие большего, дополнительно вызывают check_salon_permission.
    """
    resolved_id = await get_user_primary_salon_id(db, current_user.id, salon_id)
    if resolved_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="У вас пока нет привязанного салона. Заполните заявку на подключение."
        )
    # eager load photos: SalonResponse сериализует salon.photos, а у AsyncSession
    # нет implicit lazy load для relationship (тот же класс бага, что был в
    # chat.py) — грузим сразу, чтобы ни один потребитель этой зависимости
    # не padал на сериализации.
    salon = (await db.execute(
        select(Salon).options(selectinload(Salon.photos)).where(Salon.id == resolved_id)
    )).scalar_one_or_none()
    if salon is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Салон не найден")
    return salon


# Оставлено для обратной совместимости импортов из других модулей.
get_owner_salon = get_current_salon


# ========== POST-эндпоинт (создание И обновление салона) ==========
@router.post("/my-salon")
async def create_or_update_salon(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    address: str = Form(...),
    phone: str = Form(...),
    method_override: str = Form(""),
    salon_id: Optional[int] = Form(None),
    offer_accepted: str = Form(""),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """Создание ИЛИ обновление салона через веб-форму."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # Если method_override=put — это обновление существующего салона
    if method_override == "put":
        resolved_id = await get_user_primary_salon_id(db, user.id, salon_id)
        if resolved_id is None:
            return RedirectResponse(url="/business/register-salon", status_code=302)
        try:
            await check_salon_permission(db, user, resolved_id, "manage_salon")
        except HTTPException:
            return HTMLResponse(content="Недостаточно прав для изменения салона", status_code=403)

        salon = (await db.execute(select(Salon).where(Salon.id == resolved_id))).scalar_one_or_none()
        if salon is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Салон не найден")
        salon.name = name
        salon.description = description
        salon.address = address
        salon.phone = phone
        await db.commit()
        return RedirectResponse(url="/business/dashboard?updated=1", status_code=302)

    # Иначе — создание нового салона (ЗАЯВКА). Требуем согласие с офертой;
    # салон создаётся в статусе pending (модель по умолчанию) — виден только
    # владельцу для настройки, публично не показывается и запись закрыта, пока
    # платформа не подтвердит договор (см. модерацию в админ-панели).
    if offer_accepted != "1":
        from app.web.pages.register_salon import render_register_salon_page
        return HTMLResponse(
            content=render_register_salon_page(user, error="Нужно принять условия оферты."),
            status_code=400,
        )

    # С подключённым геокодером (YANDEX_MAPS_API_KEY) адрес обязан прийти
    # с координатами из подсказок — иначе салон получил бы московские
    # координаты по умолчанию и никогда не нашёлся бы в поиске «рядом».
    # Без ключа (лок. разработка/тесты) — старое поведение с дефолтом.
    if settings.YANDEX_MAPS_API_KEY:
        if not _validate_coords(latitude, longitude):
            from app.web.pages.register_salon import render_register_salon_page
            return HTMLResponse(
                content=render_register_salon_page(
                    user, error="Выберите адрес из подсказок, чтобы мы могли определить точное расположение салона."
                ),
                status_code=400,
            )
        salon_latitude, salon_longitude = latitude, longitude
    else:
        salon_latitude, salon_longitude = 55.7558, 37.6173

    from datetime import datetime, timezone as _tz
    # Лимита на число салонов на владельца сейчас нет (тарифы нигде не enforced).
    salon = Salon(
        creator_id=user.id,
        name=name,
        description=description,
        address=address,
        phone=phone,
        latitude=salon_latitude,
        longitude=salon_longitude,
        rating=0.0,
        reviews_count=0,
        is_active=True,
        moderation_status=SalonModerationStatus.PENDING,
        offer_accepted_at=datetime.now(_tz.utc),
    )
    db.add(salon)
    await db.flush()  # получить salon.id до commit

    db.add(SalonMember(
        salon_id=salon.id,
        user_id=user.id,
        role=SalonRole.OWNER,
        is_creator=True,
        permissions=dict(OWNER_DEFAULT_PERMISSIONS),
        is_active=True,
    ))
    await db.commit()
    await db.refresh(salon)

    from app.services.notifications import notify_admins
    await notify_admins(db, "Новая заявка на подключение салона",
                        f"«{salon.name}», тел. {salon.phone}. Одобрить/отклонить — админ-панель → Заявки.")
    return RedirectResponse(url="/business/dashboard?success=1", status_code=302)


@router.post("/apply")
async def apply_business(
    request: Request,
    salon_name: str = Form(...),
    phone: str = Form(...),
    contact_name: str = Form(""),
    email: str = Form(""),
    experience: str = Form(""),
    plan: str = Form("business"),
    offer_accepted: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Заявка на подключение салона со страницы /business/checkout.

    Создаёт салон-заявку (pending), повышает пользователя до BUSINESS и заводит
    владельцем — чтобы он мог дозаполнить салон в кабинете. Публично салон не
    виден и запись закрыта до одобрения администратором (см. модерацию).
    """
    from datetime import datetime, timezone as _tz

    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Войдите или зарегистрируйтесь, чтобы подать заявку.")
    if offer_accepted != "1":
        raise HTTPException(status_code=400, detail="Нужно принять условия использования.")

    salon = Salon(
        creator_id=user.id,
        name=salon_name.strip() or "Салон",
        description="",
        address="",  # владелец дозаполнит в кабинете, пока заявка на модерации
        phone=phone.strip(),
        latitude=55.7558, longitude=37.6173,
        rating=0.0, reviews_count=0, is_active=True,
        moderation_status=SalonModerationStatus.PENDING,
        offer_accepted_at=datetime.now(_tz.utc),
        business_tier=(plan.strip() or None),
    )
    db.add(salon)
    await db.flush()
    db.add(SalonMember(
        salon_id=salon.id, user_id=user.id, role=SalonRole.OWNER,
        is_creator=True, permissions=dict(OWNER_DEFAULT_PERMISSIONS), is_active=True,
    ))
    # Повышаем до BUSINESS: владелец получает кабинет (с баннером «на модерации»),
    # но салон невидим публично и запись закрыта до одобрения.
    if user.role != UserRole.BUSINESS:
        user.role = UserRole.BUSINESS
    await db.commit()

    from app.services.notifications import notify_admins
    await notify_admins(db, "Новая заявка на подключение салона",
                        f"«{salon.name}», тел. {salon.phone}. Одобрить/отклонить — админ-панель → Заявки.")
    return {"ok": True, "redirect": "/business/dashboard?submitted=1"}


@router.delete("/my-salon")
async def delete_salon(
    salon_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Удаление салона — доступно только создателю карточки."""
    membership = await check_salon_permission(db, current_user, salon_id, "manage_salon")
    if membership is not None and not membership.is_creator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Удалить салон может только его создатель",
        )

    salon = (await db.execute(select(Salon).where(Salon.id == salon_id))).scalar_one_or_none()
    if salon is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Салон не найден")

    db.add(AdminAudit(
        actor_id=current_user.id, action="delete_salon",
        target_type="salon", target_id=salon.id, salon_id=salon.id,
        detail=f"Удалён салон «{salon.name}»",
    ))
    # Мягкое удаление: салон скрывается (is_active=False) — из каталога/записи
    # уходит, но брони/отзывы/мастера целы. Hard-delete владельцем ронял 500
    # (ORM обнулял master.salon_id NOT NULL) и снёс бы всю историю салона.
    salon.is_active = False
    await db.commit()
    return {"status": "deleted"}


@router.post("/my-salon/guest-toggle")
async def toggle_guest_booking(
    salon_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Включить/выключить приём записей без регистрации (owner/manage_salon)."""
    await check_salon_permission(db, current_user, salon_id, "manage_salon")
    salon = (await db.execute(select(Salon).where(Salon.id == salon_id))).scalar_one_or_none()
    if salon is None:
        raise HTTPException(status_code=404, detail="Салон не найден")
    salon.guest_booking_enabled = not salon.guest_booking_enabled
    await db.commit()
    return {"guest_booking_enabled": salon.guest_booking_enabled}


@router.post("/my-salon/visibility-toggle")
async def toggle_salon_visibility(
    salon_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Скрыть/показать салон на платформе (owner/manage_salon).

    В отличие от удаления — обратимо: салон и все его данные остаются как
    есть, просто убирается из каталога/поиска/записи, пока владелец сам не
    включит обратно.
    """
    await check_salon_permission(db, current_user, salon_id, "manage_salon")
    salon = (await db.execute(select(Salon).where(Salon.id == salon_id))).scalar_one_or_none()
    if salon is None:
        raise HTTPException(status_code=404, detail="Салон не найден")
    salon.is_hidden = not salon.is_hidden
    await db.commit()
    return {"is_hidden": salon.is_hidden}


@router.get("/my-salon", response_model=SalonResponse)
async def get_my_salon(
    salon: Salon = Depends(get_current_salon)
):
    """Возвращает карточку салона текущего пользователя."""
    return salon


@router.put("/my-salon", response_model=SalonResponse)
async def update_my_salon(
    update_data: SalonUpdateRequest,
    salon: Salon = Depends(get_current_salon),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Обновляет информацию о своём салоне (API)."""
    await check_salon_permission(db, current_user, salon.id, "manage_salon")

    if update_data.name is not None:
        salon.name = update_data.name
    if update_data.description is not None:
        salon.description = update_data.description
    if update_data.phone is not None:
        salon.phone = update_data.phone
    if update_data.address is not None:
        address_changed = update_data.address != salon.address
        # Меняем адрес и подключён геокодер → координаты из подсказок
        # обязательны, иначе салон останется на старой/дефолтной точке.
        if address_changed and settings.YANDEX_MAPS_API_KEY:
            if not _validate_coords(update_data.latitude, update_data.longitude):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Выберите адрес из подсказок, чтобы определить точные координаты",
                )
        salon.address = update_data.address
    if _validate_coords(update_data.latitude, update_data.longitude):
        salon.latitude = update_data.latitude
        salon.longitude = update_data.longitude
    if update_data.working_hours is not None:
        salon.working_hours = update_data.working_hours

    # Обработка фото
    if update_data.photos is not None:
        # Удаляем все старые фото
        old_photos = await db.execute(
            select(SalonPhoto).where(SalonPhoto.salon_id == salon.id)
        )
        for photo in old_photos.scalars().all():
            await db.delete(photo)
        # Добавляем новые
        for url in update_data.photos:
            new_photo = SalonPhoto(salon_id=salon.id, url=url)
            db.add(new_photo)

    if update_data.logo_url is not None:
        salon.logo_url = update_data.logo_url

    await db.commit()
    await db.refresh(salon)

    # Загружаем фото для ответа
    photos_result = await db.execute(select(SalonPhoto).where(SalonPhoto.salon_id == salon.id))
    salon.photos = list(photos_result.scalars().all())

    return salon


@router.get("/my-salon/masters", response_model=List[MasterResponse])
async def get_my_masters(
    salon: Salon = Depends(get_current_salon),
    db: AsyncSession = Depends(get_db)
):
    """Список всех мастеров моего салона."""
    result = await db.execute(
        select(Master).where(Master.salon_id == salon.id)
    )
    return result.scalars().all()


@router.get("/my-salon/promotions", response_model=List[PromotionResponse])
async def get_my_promotions(
    salon: Salon = Depends(get_current_salon),
    db: AsyncSession = Depends(get_db)
):
    """Список акций моего салона."""
    result = await db.execute(
        select(Promotion).where(Promotion.salon_id == salon.id)
    )
    return result.scalars().all()


@router.post("/my-salon/promotions", response_model=PromotionResponse, status_code=status.HTTP_201_CREATED)
async def create_promotion(
    promotion_data: PromotionResponse,
    salon: Salon = Depends(get_current_salon),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Создаёт новую акцию для салона."""
    await check_salon_permission(db, current_user, salon.id, "manage_promotions")

    new_promotion = Promotion(
        salon_id=salon.id,
        title=promotion_data.title,
        description=promotion_data.description,
        tag=promotion_data.tag
    )
    db.add(new_promotion)
    await db.commit()
    await db.refresh(new_promotion)
    return new_promotion


@router.post("/my-salon/promotions/{promo_id}/update")
async def update_promotion_web(
    promo_id: int,
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    tag: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    """Обновление акции через веб-форму (требуется право manage_promotions)."""
    from app.web.auth import get_current_user_from_cookie
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    promo = (await db.execute(select(Promotion).where(Promotion.id == promo_id))).scalar_one_or_none()
    if not promo:
        return HTMLResponse(content="Акция не найдена", status_code=404)

    try:
        await check_salon_permission(db, user, promo.salon_id, "manage_promotions")
    except HTTPException:
        return HTMLResponse(content="Недостаточно прав для управления акциями", status_code=403)

    promo.title = title
    promo.description = description
    promo.tag = tag
    await db.commit()

    return RedirectResponse(url="/business/dashboard?tab=promos&updated=1", status_code=302)


@router.get("/my-salon/dashboard")
async def get_business_dashboard(
    salon: Salon = Depends(get_current_salon),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Возвращает сводку для панели бизнеса."""
    from app.models.models import Booking, BookingStatus, PAID_BOOKING_STATUSES
    from sqlalchemy import func as sql_func
    from datetime import datetime, timedelta

    masters_count = len(salon.masters)

    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    bookings_today = await db.execute(
        select(sql_func.count(Booking.id)).where(
            Booking.master_id.in_([m.id for m in salon.masters]),
            Booking.start_time >= today_start,
            Booking.start_time < today_end
        )
    )
    today_count = bookings_today.scalar() or 0

    # Выручка — только тем, у кого есть view_finances (создатель — всегда).
    revenue = None
    membership = await get_salon_membership(db, current_user.id, salon.id)
    can_view_finances = membership is not None and (
        membership.is_creator or membership.permissions.get("view_finances", False)
    )
    if can_view_finances:
        month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        revenue_month = await db.execute(
            select(sql_func.sum(Booking.final_price)).where(
                Booking.master_id.in_([m.id for m in salon.masters]),
                Booking.start_time >= month_start,
                Booking.status.in_(PAID_BOOKING_STATUSES)
            )
        )
        revenue = revenue_month.scalar() or 0

    return {
        "salon_name": salon.name,
        "masters_count": masters_count,
        "today_bookings": today_count,
        "monthly_revenue": revenue,
        "rating": salon.rating,
        "reviews_count": salon.reviews_count
    }


@router.get("/my-salon/analytics")
async def get_salon_analytics(
    salon_id: int,
    granularity: Literal["day", "week", "month", "year"] = "day",
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Гранулярная аналитика выручки/записей салона (день/неделя/месяц/год,
    произвольный период) для вкладки «Аналитика» и внешних интеграций.

    Без date_from/date_to подставляется разумное окно по умолчанию под
    гранулярность (см. AnalyticsService.default_range).
    """
    await check_salon_permission(db, current_user, salon_id, "view_finances")

    default_from, default_to = AnalyticsService.default_range(granularity)
    date_from = date_from or default_from
    date_to = date_to or default_to

    master_ids = await AnalyticsService.master_ids_for_salon(db, salon_id)
    try:
        points = await AnalyticsService.revenue_series(db, master_ids, granularity, date_from, date_to)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    top_services = await AnalyticsService.top_services(db, master_ids, date_from, date_to)

    total_revenue = sum(p["revenue"] for p in points)
    total_bookings = sum(p["bookings_total"] for p in points)
    total_paid = sum(p["bookings_paid"] for p in points)

    return {
        "granularity": granularity,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "points": points,
        "summary": {
            "total_revenue": total_revenue,
            "total_bookings": total_bookings,
            "avg_check": (total_revenue // total_paid) if total_paid else 0,
        },
        "top_services": top_services,
    }


@router.get("/my-salon/analytics/day")
async def get_salon_analytics_day(
    salon_id: int,
    date: date,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Список операций за один день — для аккордеона «детали дня» под графиком
    аналитики (доступно при группировке по дням)."""
    await check_salon_permission(db, current_user, salon_id, "view_finances")
    master_ids = await AnalyticsService.master_ids_for_salon(db, salon_id)
    operations = await AnalyticsService.day_operations(db, master_ids, date)
    return {"date": date.isoformat(), "operations": operations}


@router.get("/my-salon/bookings")
async def list_my_salon_bookings(
    salon: Salon = Depends(get_current_salon),
    db: AsyncSession = Depends(get_db),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    master_id: Optional[int] = None,
    status_filter: Optional[str] = None,
):
    """Список броней салона с фильтрами — данные для вкладки «Записи» /
    внешних интеграций. Формат дат: YYYY-MM-DD."""
    from datetime import datetime, timedelta
    from app.models.models import Booking, BookingStatus, Service as ServiceModel, Master as MasterModel

    master_ids_result = await db.execute(select(MasterModel.id).where(MasterModel.salon_id == salon.id))
    master_ids = [row[0] for row in master_ids_result.all()]
    if not master_ids:
        return []

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        start = datetime.strptime(date_from, "%Y-%m-%d") if date_from else today - timedelta(days=30)
        end = (datetime.strptime(date_to, "%Y-%m-%d") if date_to else today) + timedelta(days=1)
    except ValueError:
        raise HTTPException(status_code=400, detail="Формат даты: YYYY-MM-DD")

    query = (
        select(Booking, ServiceModel)
        .join(ServiceModel, ServiceModel.id == Booking.service_id)
        .where(Booking.master_id.in_(master_ids), Booking.start_time >= start, Booking.start_time < end)
    )
    if master_id:
        query = query.where(Booking.master_id == master_id)
    if status_filter:
        try:
            query = query.where(Booking.status == BookingStatus(status_filter))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректный статус брони")

    result = await db.execute(query.order_by(Booking.start_time.desc()).limit(200))
    return [
        {
            "id": b.id,
            "client_id": b.client_id,
            "master_id": b.master_id,
            "service_name": s.name,
            "start_time": b.start_time.isoformat(),
            "status": b.status.value,
            "final_price": b.final_price or s.price,
            "consumption_reported": b.consumption_reported,
        }
        for b, s in result.all()
    ]


@router.post("/my-salon/promotions/web")
async def create_promotion_web(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    tag: str = Form(...),
    salon_id: Optional[int] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """Создание акции через веб-форму."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    resolved_id = await get_user_primary_salon_id(db, user.id, salon_id)
    if resolved_id is None:
        return RedirectResponse(url="/business/register-salon", status_code=302)
    try:
        await check_salon_permission(db, user, resolved_id, "manage_promotions")
    except HTTPException:
        return HTMLResponse(content="Недостаточно прав для управления акциями", status_code=403)

    promo = Promotion(
        salon_id=resolved_id,
        title=title,
        description=description,
        tag=tag
    )
    db.add(promo)
    await db.commit()

    return RedirectResponse(url="/business/dashboard?tab=promos&added=1", status_code=302)


@router.post("/my-salon/promotions/{promo_id}/delete")
async def delete_promotion_web(
    promo_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Удаление акции."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    promo = (await db.execute(select(Promotion).where(Promotion.id == promo_id))).scalar_one_or_none()
    if not promo:
        return HTMLResponse(content="Акция не найдена", status_code=404)

    try:
        await check_salon_permission(db, user, promo.salon_id, "manage_promotions")
    except HTTPException:
        return HTMLResponse(content="Недостаточно прав для управления акциями", status_code=403)

    await db.delete(promo)
    await db.commit()

    return RedirectResponse(url="/business/dashboard?tab=promos&deleted=1", status_code=302)


# ========== Карточка клиента: заметки ==========
class ClientNoteCreateRequest(BaseModel):
    text: str


@router.post("/my-salon/clients/{client_id}/notes", status_code=status.HTTP_201_CREATED)
async def create_client_note(
    client_id: int,
    note_data: ClientNoteCreateRequest,
    salon: Salon = Depends(get_current_salon),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Добавляет заметку на карточку клиента. Доступно любому активному
    участнику салона — как и сама вкладка «Клиенты», без отдельного права."""
    text = note_data.text.strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Текст заметки не может быть пустым")

    note = ClientNote(
        salon_id=salon.id,
        client_id=client_id,
        author_id=current_user.id,
        text=text,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return {"id": note.id, "text": note.text, "created_at": note.created_at.isoformat()}


# ========== Promo-модели салона (вкладка «Модели») ==========
class SalonModelCreateRequest(BaseModel):
    phone: str
    stage_name: Optional[str] = None
    bio: Optional[str] = None
    photo_url: Optional[str] = None


@router.get("/my-salon/models")
async def list_salon_models(
    salon: Salon = Depends(get_current_salon),
    db: AsyncSession = Depends(get_db),
):
    """Список promo-моделей, привязанных к салону."""
    result = await db.execute(
        select(SalonModel, User)
        .join(User, User.id == SalonModel.user_id)
        .where(SalonModel.salon_id == salon.id, SalonModel.is_active == True)
        .order_by(SalonModel.created_at.desc())
    )
    return [
        {
            "id": sm.id, "user_id": u.id, "full_name": u.full_name, "phone": u.phone,
            "stage_name": sm.stage_name, "bio": sm.bio, "photo_url": sm.photo_url,
        }
        for sm, u in result.all()
    ]


@router.post("/my-salon/models", status_code=status.HTTP_201_CREATED)
async def attach_salon_model(
    payload: SalonModelCreateRequest,
    salon: Salon = Depends(get_current_salon),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Привязывает существующего пользователя с ролью MODEL к салону
    (кастинг/сотрудничество). Новых пользователей здесь не создаём —
    модели регистрируются сами через «Стать моделью»."""
    await check_salon_permission(db, current_user, salon.id, "manage_masters")

    model_user = (await db.execute(select(User).where(User.phone == payload.phone))).scalar_one_or_none()
    if not model_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь с таким телефоном не найден")
    if model_user.role != UserRole.MODEL:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="У этого пользователя нет роли «модель»")

    existing = (await db.execute(
        select(SalonModel).where(SalonModel.salon_id == salon.id, SalonModel.user_id == model_user.id)
    )).scalar_one_or_none()
    if existing:
        if existing.is_active:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Эта модель уже привязана к салону")
        existing.is_active = True
        existing.stage_name = payload.stage_name
        existing.bio = payload.bio
        existing.photo_url = payload.photo_url
        await db.commit()
        return {"id": existing.id, "status": "reattached"}

    salon_model = SalonModel(
        salon_id=salon.id, user_id=model_user.id,
        stage_name=payload.stage_name, bio=payload.bio, photo_url=payload.photo_url,
    )
    db.add(salon_model)
    await db.commit()
    await db.refresh(salon_model)
    return {"id": salon_model.id, "status": "attached"}


@router.delete("/my-salon/models/{model_id}")
async def detach_salon_model(
    model_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отвязывает promo-модель от салона (мягкое удаление)."""
    salon_model = (await db.execute(select(SalonModel).where(SalonModel.id == model_id))).scalar_one_or_none()
    if not salon_model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Модель не найдена")

    await check_salon_permission(db, current_user, salon_model.salon_id, "manage_masters")

    salon_model.is_active = False
    await db.commit()
    return {"status": "detached"}
