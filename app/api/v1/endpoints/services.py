# app/api/v1/endpoints/services.py
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models.models import Service, Master
from app.api.deps import check_salon_permission
from app.web.service_categories import suggest_category, VALID_CATEGORY_SLUGS

router = APIRouter()


def _resolve_category(chosen: str, name: str) -> str | None:
    """Гибрид: если владелец явно выбрал валидную категорию — берём её; иначе
    подсказываем матчером по названию (первый матч, может быть None)."""
    chosen = (chosen or "").strip()
    if chosen in VALID_CATEGORY_SLUGS:
        return chosen
    return suggest_category(name)


@router.post("/services/create")
async def create_service_web(
    request: Request,
    master_ids: list[int] = Form(...),
    name: str = Form(...),
    price: int = Form(...),
    price_max: str = Form(""),
    price_mode: str = Form("fixed"),
    duration_minutes: int = Form(...),
    description: str = Form(""),
    category: str = Form(""),
    is_model_practice: bool = Form(False),
    model_quota: str = Form(""),
    model_desired_date: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    """Добавление услуги мастеру.

    is_model_practice — спецуслуга для отработки на моделях (своя цена/
    длительность, не показывается обычным клиентам, только в мэтчинге моделей).
    model_quota — сколько моделей нужно набрать на неё, пусто = без квоты
    (открытость тогда управляется только вручную, model_seeking_open).
    model_desired_date — желаемая дата отработки, чисто информационная.
    """
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    masters_result = await db.execute(select(Master).where(Master.id.in_(master_ids)))
    selected_masters = masters_result.scalars().all()
    if not selected_masters or len(selected_masters) != len(set(master_ids)):
        return HTMLResponse(content="Один или несколько мастеров не найдены", status_code=404)
    master = selected_masters[0]

    try:
        await check_salon_permission(db, user, master.salon_id, "manage_masters")
    except HTTPException:
        return HTMLResponse(content="Недостаточно прав для управления услугами", status_code=403)

    try:
        parsed_quota = int(model_quota) if model_quota.strip() else None
        parsed_desired_date = date.fromisoformat(model_desired_date) if model_desired_date.strip() else None
    except ValueError:
        return HTMLResponse(content="Некорректный формат квоты моделей или желаемой даты отработки", status_code=400)

    if price < 0:
        return HTMLResponse(content="Цена не может быть отрицательной", status_code=400)
    if price_mode == "range" and not price_max.strip():
        return HTMLResponse(content="Для диапазона укажите верхнюю границу цены", status_code=400)
    try:
        parsed_price_max = int(price_max) if price_mode == "range" else None
    except ValueError:
        return HTMLResponse(content="Некорректная верхняя граница цены", status_code=400)
    if parsed_price_max is not None and (parsed_price_max < 0 or parsed_price_max < price):
        return HTMLResponse(content="Верхняя граница цены не может быть меньше нижней", status_code=400)

    if any(item.salon_id != master.salon_id for item in selected_masters):
        return HTMLResponse(content="Все мастера услуги должны быть из одного салона", status_code=403)

    service = Service(
        master_id=master.id,
        name=name,
        price=price,
        price_max=parsed_price_max,
        duration_minutes=duration_minutes,
        description=description,
        category=_resolve_category(category, name),
        is_model_practice=is_model_practice,
        model_quota=parsed_quota,
        model_desired_date=parsed_desired_date,
    )
    db.add(service)
    await db.flush()
    service.assigned_masters = selected_masters
    await db.commit()

    return RedirectResponse(url="/business/dashboard?tab=services&added=1", status_code=302)


@router.post("/services/{service_id}/update")
async def update_service_web(
    service_id: int,
    request: Request,
    master_ids: list[int] = Form(...),
    name: str = Form(...),
    price: int = Form(...),
    price_max: str = Form(""),
    price_mode: str = Form("fixed"),
    duration_minutes: int = Form(...),
    description: str = Form(""),
    category: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    """Обновление услуги."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    service = (await db.execute(
        select(Service).options(selectinload(Service.assigned_masters)).where(Service.id == service_id)
    )).scalar_one_or_none()
    if not service:
        return HTMLResponse(content="Услуга не найдена", status_code=404)

    master = (await db.execute(select(Master).where(Master.id == service.master_id))).scalar_one_or_none()
    if not master:
        return HTMLResponse(content="Мастер не найден", status_code=404)

    try:
        await check_salon_permission(db, user, master.salon_id, "manage_masters")
    except HTTPException:
        return HTMLResponse(content="Недостаточно прав для управления услугами", status_code=403)

    selected_masters = (await db.execute(
        select(Master).where(Master.id.in_(master_ids))
    )).scalars().all()
    if not selected_masters or len(selected_masters) != len(set(master_ids)):
        return HTMLResponse(content="Один или несколько мастеров не найдены", status_code=404)
    if any(item.salon_id != master.salon_id for item in selected_masters):
        return HTMLResponse(content="Все мастера услуги должны быть из одного салона", status_code=403)

    if price < 0:
        return HTMLResponse(content="Цена не может быть отрицательной", status_code=400)
    if price_mode == "range" and not price_max.strip():
        return HTMLResponse(content="Для диапазона укажите верхнюю границу цены", status_code=400)
    try:
        parsed_price_max = int(price_max) if price_mode == "range" else None
    except ValueError:
        return HTMLResponse(content="Некорректная верхняя граница цены", status_code=400)
    if parsed_price_max is not None and (parsed_price_max < 0 or parsed_price_max < price):
        return HTMLResponse(content="Верхняя граница цены не может быть меньше нижней", status_code=400)

    service.master_id = selected_masters[0].id
    service.assigned_masters = selected_masters
    service.name = name
    service.price = price
    service.price_max = parsed_price_max
    service.duration_minutes = duration_minutes
    service.description = description
    service.category = _resolve_category(category, name)
    await db.commit()

    return RedirectResponse(url="/business/dashboard?tab=services&updated=1", status_code=302)


@router.post("/services/{service_id}/delete")
async def delete_service_web(
    service_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Удаление услуги (мягкое удаление)."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    service = (await db.execute(select(Service).where(Service.id == service_id))).scalar_one_or_none()
    if not service:
        return HTMLResponse(content="Услуга не найдена", status_code=404)

    master = (await db.execute(select(Master).where(Master.id == service.master_id))).scalar_one_or_none()
    if not master:
        return HTMLResponse(content="Мастер не найден", status_code=404)

    try:
        await check_salon_permission(db, user, master.salon_id, "manage_masters")
    except HTTPException:
        return HTMLResponse(content="Недостаточно прав для управления услугами", status_code=403)

    # Мягкое удаление
    service.is_active = False
    await db.commit()

    return RedirectResponse(url="/business/dashboard?tab=services&deleted=1", status_code=302)