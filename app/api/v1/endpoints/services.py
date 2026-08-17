# app/api/v1/endpoints/services.py
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

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
    master_id: int = Form(...),
    name: str = Form(...),
    price: int = Form(...),
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

    master = (await db.execute(select(Master).where(Master.id == master_id))).scalar_one_or_none()
    if not master:
        return HTMLResponse(content="Мастер не найден", status_code=404)

    try:
        await check_salon_permission(db, user, master.salon_id, "manage_masters")
    except HTTPException:
        return HTMLResponse(content="Недостаточно прав для управления услугами", status_code=403)

    try:
        parsed_quota = int(model_quota) if model_quota.strip() else None
        parsed_desired_date = date.fromisoformat(model_desired_date) if model_desired_date.strip() else None
    except ValueError:
        return HTMLResponse(content="Некорректный формат квоты моделей или желаемой даты отработки", status_code=400)

    service = Service(
        master_id=master_id,
        name=name,
        price=price,
        duration_minutes=duration_minutes,
        description=description,
        category=_resolve_category(category, name),
        is_model_practice=is_model_practice,
        model_quota=parsed_quota,
        model_desired_date=parsed_desired_date,
    )
    db.add(service)
    await db.commit()

    return RedirectResponse(url="/business/dashboard?tab=services&added=1", status_code=302)


@router.post("/services/{service_id}/update")
async def update_service_web(
    service_id: int,
    request: Request,
    master_id: int = Form(...),
    name: str = Form(...),
    price: int = Form(...),
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

    # Новый мастер услуги (если поменяли) должен принадлежать тому же салону
    if master_id != service.master_id:
        new_master = (await db.execute(select(Master).where(Master.id == master_id))).scalar_one_or_none()
        if not new_master or new_master.salon_id != master.salon_id:
            return HTMLResponse(content="Нет доступа", status_code=403)

    service.master_id = master_id
    service.name = name
    service.price = price
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