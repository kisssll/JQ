# app/api/v1/endpoints/inventory.py
from typing import Literal, Optional
from datetime import date as date_cls
from fastapi import APIRouter, Depends, HTTPException, Request, Form, status
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, delete

from app.db.session import get_db
from app.models.models import (
    InventoryItem, InventoryMovement, InventoryMovementType, Master, User, UserRole,
    Booking, WarehouseAssignment, WarehouseRequestType, Equipment, EquipmentStatus, Service,
)
from app.api.deps import check_salon_permission, get_current_user, require_role
from app.services.inventory_service import InventoryService, InventoryError
from app.services.notifications import (
    notify_warehouse_request_created,
    notify_warehouse_request_resolved,
    notify_warehouse_low_stock,
)

router = APIRouter()


class CatalogProductBody(BaseModel):
    kind: Literal["consumable", "equipment"]
    assignment_type: Literal["salon", "master", "service"] = "salon"
    name: str = Field(min_length=1, max_length=100)
    unit: str = Field(min_length=1, max_length=20)
    quantity: float = Field(ge=0)
    target_quantity: float = Field(default=0, ge=0)
    min_quantity: float = Field(ge=0)
    cost_per_unit: int = Field(ge=0)
    master_ids: list[int] = Field(default_factory=list)
    service_ids: list[int] = Field(default_factory=list)
    status: Literal["working", "broken", "lost"] = "working"
    purchased_at: Optional[date_cls] = None
    service_life_months: Optional[int] = Field(default=None, ge=1)


async def _master_or_404(db: AsyncSession, master_id: int) -> Master:
    master = (await db.execute(select(Master).where(Master.id == master_id))).scalar_one_or_none()
    if not master:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Мастер не найден")
    return master


async def _validate_catalog_assignments(
    db: AsyncSession, salon_id: int, assignment_type: str,
    master_ids: list[int], service_ids: list[int],
) -> None:
    master_ids = list(dict.fromkeys(master_ids))
    service_ids = list(dict.fromkeys(service_ids))
    if master_ids and service_ids:
        raise HTTPException(status_code=400, detail="Выберите мастеров или услуги, но не оба варианта")
    if assignment_type == "salon" and (master_ids or service_ids):
        raise HTTPException(status_code=400, detail="Для общего склада не выбираются мастера или услуги")
    if assignment_type == "master" and (not master_ids or service_ids):
        raise HTTPException(status_code=400, detail="Выберите одного или нескольких мастеров")
    if assignment_type == "service" and (not service_ids or master_ids):
        raise HTTPException(status_code=400, detail="Выберите одну или несколько услуг")

    salon_master_ids = set((await db.execute(
        select(Master.id).where(Master.salon_id == salon_id)
    )).scalars().all())
    if not set(master_ids).issubset(salon_master_ids):
        raise HTTPException(status_code=400, detail="Выбраны мастера не из этого салона")
    if service_ids:
        service_rows = (await db.execute(
            select(Service.id).where(
                Service.id.in_(service_ids),
                or_(
                    Service.master_id.in_(salon_master_ids),
                    Service.assigned_masters.any(Master.id.in_(salon_master_ids)),
                ),
                Service.is_active == True,
            )
        )).all()
        if len(service_rows) != len(service_ids):
            raise HTTPException(status_code=400, detail="Выбраны услуги не из этого салона")


async def _save_assignments(
    db: AsyncSession, *, kind: str, product_id: int, master_ids: list[int], service_ids: list[int],
) -> None:
    target_column = (
        WarehouseAssignment.inventory_item_id if kind == "consumable"
        else WarehouseAssignment.equipment_id
    )
    await db.execute(delete(WarehouseAssignment).where(target_column == product_id))
    for master_id in dict.fromkeys(master_ids):
        db.add(WarehouseAssignment(
            inventory_item_id=product_id if kind == "consumable" else None,
            equipment_id=product_id if kind == "equipment" else None,
            master_id=master_id,
        ))
    for service_id in dict.fromkeys(service_ids):
        db.add(WarehouseAssignment(
            inventory_item_id=product_id if kind == "consumable" else None,
            equipment_id=product_id if kind == "equipment" else None,
            service_id=service_id,
        ))


def _validate_catalog_body(body: CatalogProductBody) -> None:
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Укажите название товара")
    if not body.unit.strip():
        raise HTTPException(status_code=400, detail="Укажите единицу измерения")


async def _catalog_product_or_404(db: AsyncSession, salon_id: int, kind: str, product_id: int):
    if kind == "consumable":
        product = (await db.execute(select(InventoryItem).where(
            InventoryItem.id == product_id, InventoryItem.salon_id == salon_id
        ))).scalar_one_or_none()
    else:
        product = (await db.execute(select(Equipment).where(
            Equipment.id == product_id, Equipment.salon_id == salon_id
        ))).scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Товар не найден")
    return product


def _catalog_response(product, kind: str) -> dict:
    return {
        "id": product.id,
        "kind": kind,
        "name": product.name,
        "unit": product.unit,
        "quantity": product.quantity,
        "target_quantity": product.target_quantity,
        "min_quantity": product.min_quantity,
        "cost_per_unit": product.cost_per_unit,
        "status": product.status.value if kind == "equipment" else None,
        "is_active": product.is_active,
    }





# ========== Админ/владелец: номенклатура и приход (веб-формы, как services.py) ==========

@router.post("/master/{master_id}/items")
async def create_inventory_item_web(
    master_id: int,
    request: Request,
    name: str = Form(...),
    unit: str = Form(...),
    cost_per_unit: int = Form(...),
    min_quantity: float = Form(0),
    db: AsyncSession = Depends(get_db),
):
    """Добавляет новую позицию номенклатуры на мини-склад мастера."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    master = await _master_or_404(db, master_id)
    try:
        await check_salon_permission(db, user, master.salon_id, "manage_inventory")
    except HTTPException:
        return HTMLResponse(content="Недостаточно прав для управления складом", status_code=403)

    item = InventoryItem(
        salon_id=master.salon_id, master_id=master_id, name=name, unit=unit,
        cost_per_unit=cost_per_unit, min_quantity=min_quantity,
    )
    db.add(item)
    await db.flush()
    db.add(WarehouseAssignment(inventory_item_id=item.id, master_id=master_id))
    await db.commit()
    if min_quantity > 0:
        await notify_warehouse_low_stock(
            db, salon_id=master.salon_id, item_name=item.name, quantity=item.quantity,
            unit=item.unit, min_quantity=item.min_quantity,
        )

    return RedirectResponse(url="/business/dashboard?tab=warehouse&item_added=1", status_code=302)


@router.post("/master/{master_id}/receive")
async def receive_stock_web(
    master_id: int,
    request: Request,
    item_id: int = Form(...),
    quantity: float = Form(...),
    comment: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Приход расходников на мини-склад мастера."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    master = await _master_or_404(db, master_id)
    try:
        await check_salon_permission(db, user, master.salon_id, "manage_inventory")
    except HTTPException:
        return HTMLResponse(content="Недостаточно прав для управления складом", status_code=403)

    try:
        available_item_ids = {
            item.id for item in await InventoryService.get_master_stock(db, master_id)
        }
        if item_id not in available_item_ids:
            raise HTTPException(status_code=403, detail="Позиция не относится к этому салону или мастеру")
        await InventoryService.receive_stock(db, item_id=item_id, quantity=quantity, comment=comment, actor=user)
    except HTTPException:
        raise
    except InventoryError as e:
        return HTMLResponse(content=e.message, status_code=e.status)

    return RedirectResponse(url="/business/dashboard?tab=warehouse&received=1", status_code=302)


@router.get("/master/{master_id}/stock")
async def get_master_stock_api(
    master_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Остатки мини-склада мастера (для владельца/админа салона)."""
    master = await _master_or_404(db, master_id)
    await check_salon_permission(db, current_user, master.salon_id, "manage_inventory")
    items = await InventoryService.get_master_stock(db, master_id)
    return [
        {"id": i.id, "name": i.name, "unit": i.unit, "quantity": i.quantity,
         "cost_per_unit": i.cost_per_unit, "min_quantity": i.min_quantity}
        for i in items
    ]


# ========== Инвентаризация (JSON — динамический список позиций) ==========

@router.post("/master/{master_id}/audit/start")
async def start_audit_web(
    master_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Открывает акт инвентаризации мини-склада мастера."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    master = await _master_or_404(db, master_id)
    if master.user_id != user.id:
        try:
            await check_salon_permission(db, user, master.salon_id, "manage_inventory")
        except HTTPException:
            return HTMLResponse(content="Недостаточно прав для управления складом", status_code=403)

    try:
        audit = await InventoryService.start_audit(
            db, salon_id=master.salon_id, master_id=master_id, actor=user
        )
    except InventoryError as e:
        return HTMLResponse(content=e.message, status_code=e.status)

    return_url = (
        "/master/inventory" if master.user_id == user.id
        else f"/business/dashboard?salon_id={master.salon_id}&tab=warehouse&audit_id={audit.id}"
    )
    if master.user_id == user.id:
        return_url += f"?audit_id={audit.id}"
    return RedirectResponse(url=return_url, status_code=302)


@router.post("/salon/{salon_id}/audit/start")
async def start_salon_audit_web(
    salon_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Открывает инвентаризацию всех активных позиций салона."""
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    try:
        await check_salon_permission(db, user, salon_id, "manage_inventory")
        audit = await InventoryService.start_audit(db, salon_id=salon_id, actor=user)
    except HTTPException:
        return HTMLResponse(content="Недостаточно прав для управления складом", status_code=403)
    except InventoryError as e:
        return HTMLResponse(content=e.message, status_code=e.status)

    return RedirectResponse(
        url=f"/business/dashboard?tab=warehouse&audit_id={audit.id}",
        status_code=302,
    )


class AuditItemReviewRequest(BaseModel):
    action: Literal["correct", "adjust", "archive"]
    actual_quantity: Optional[float] = Field(default=None, ge=0)


class AuditConfirmRequest(BaseModel):
    actual_quantities: Optional[dict[int, float]] = None


async def _authorize_audit(
    db: AsyncSession, audit, current_user: User,
) -> None:
    if audit.master_id is not None:
        master = await _master_or_404(db, audit.master_id)
        if master.user_id == current_user.id:
            return
    await check_salon_permission(db, current_user, audit.salon_id, "manage_inventory")


@router.post("/audit/{audit_id}/items/{audit_item_id}")
async def review_audit_item_api(
    audit_id: int,
    audit_item_id: int,
    body: AuditItemReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.models import InventoryAudit

    audit = (await db.execute(
        select(InventoryAudit).where(InventoryAudit.id == audit_id)
    )).scalar_one_or_none()
    if not audit:
        raise HTTPException(status_code=404, detail="Акт не найден")
    await _authorize_audit(db, audit, current_user)
    try:
        row = await InventoryService.review_audit_item(
            db,
            audit_id=audit_id,
            audit_item_id=audit_item_id,
            action=body.action,
            actual_quantity=body.actual_quantity,
        )
    except InventoryError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    return {"id": row.id, "is_reviewed": row.is_reviewed}


@router.post("/salon/{salon_id}/catalog")
async def create_catalog_product(
    salon_id: int,
    body: CatalogProductBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_salon_permission(db, current_user, salon_id, "manage_inventory")
    _validate_catalog_body(body)
    await _validate_catalog_assignments(
        db, salon_id, body.assignment_type, body.master_ids, body.service_ids
    )

    if body.kind == "consumable":
        product = InventoryItem(
            salon_id=salon_id,
            master_id=None,
            name=body.name.strip(),
            unit=body.unit.strip(),
            quantity=body.quantity,
            target_quantity=body.target_quantity,
            cost_per_unit=body.cost_per_unit,
            min_quantity=body.min_quantity,
        )
    else:
        product = Equipment(
            salon_id=salon_id,
            name=body.name.strip(),
            unit=body.unit.strip(),
            quantity=body.quantity,
            target_quantity=body.target_quantity,
            min_quantity=0,
            cost_per_unit=body.cost_per_unit,
            status=EquipmentStatus(body.status),
            purchased_at=body.purchased_at,
            service_life_months=body.service_life_months,
        )
    db.add(product)
    await db.flush()
    await _save_assignments(
        db, kind=body.kind, product_id=product.id,
        master_ids=body.master_ids, service_ids=body.service_ids,
    )
    if body.quantity > 0:
        db.add(InventoryMovement(
            item_id=product.id if body.kind == "consumable" else None,
            equipment_id=product.id if body.kind == "equipment" else None,
            type=InventoryMovementType.RECEIPT,
            delta=body.quantity,
            unit_cost_snapshot=body.cost_per_unit,
            created_by_id=current_user.id,
            comment="Первоначальный остаток",
        ))
    await db.commit()
    await db.refresh(product)

    if body.kind == "consumable" and body.min_quantity > 0 and body.quantity <= body.min_quantity:
        await notify_warehouse_low_stock(
            db, salon_id=salon_id, item_name=product.name, quantity=product.quantity,
            unit=product.unit, min_quantity=product.min_quantity,
        )
    return _catalog_response(product, body.kind)


@router.put("/salon/{salon_id}/catalog/{kind}/{product_id}")
async def update_catalog_product(
    salon_id: int,
    kind: Literal["consumable", "equipment"],
    product_id: int,
    body: CatalogProductBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_salon_permission(db, current_user, salon_id, "manage_inventory")
    if body.kind != kind:
        raise HTTPException(status_code=400, detail="Тип товара не совпадает")
    _validate_catalog_body(body)
    await _validate_catalog_assignments(
        db, salon_id, body.assignment_type, body.master_ids, body.service_ids
    )
    product = await _catalog_product_or_404(db, salon_id, kind, product_id)

    old_quantity = product.quantity
    old_min_quantity = product.min_quantity
    if body.quantity != old_quantity:
        if body.quantity < 0:
            raise HTTPException(status_code=400, detail="Остаток не может быть отрицательным")
        delta = body.quantity - old_quantity
        db.add(InventoryMovement(
            item_id=product_id if kind == "consumable" else None,
            equipment_id=product_id if kind == "equipment" else None,
            type=InventoryMovementType.ADJUSTMENT,
            delta=delta,
            unit_cost_snapshot=product.cost_per_unit or 0,
            created_by_id=current_user.id,
            comment="Корректировка из таблицы склада",
        ))
        product.quantity = body.quantity

    product.name = body.name.strip()
    product.unit = body.unit.strip()
    product.target_quantity = body.target_quantity
    product.min_quantity = body.min_quantity if kind == "consumable" else 0
    product.cost_per_unit = body.cost_per_unit
    if kind == "equipment":
        product.status = EquipmentStatus(body.status)
        product.purchased_at = body.purchased_at
        product.service_life_months = body.service_life_months
    await _save_assignments(
        db, kind=kind, product_id=product_id,
        master_ids=body.master_ids, service_ids=body.service_ids,
    )
    await db.commit()
    await db.refresh(product)
    if kind == "consumable" and product.is_active:
        await InventoryService.notify_if_low_stock_transition(
            db, salon_id=salon_id, name=product.name, unit=product.unit,
            old_quantity=old_quantity, old_min_quantity=old_min_quantity,
            quantity=product.quantity, min_quantity=product.min_quantity,
        )
    return _catalog_response(product, kind)


@router.post("/salon/{salon_id}/catalog/{kind}/{product_id}/toggle-active")
async def toggle_catalog_product_active(
    salon_id: int,
    kind: Literal["consumable", "equipment"],
    product_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_salon_permission(db, current_user, salon_id, "manage_inventory")
    product = await _catalog_product_or_404(db, salon_id, kind, product_id)
    product.is_active = not product.is_active
    await db.commit()
    return {"id": product.id, "is_active": product.is_active}


@router.get("/salon/{salon_id}/catalog/{kind}/{product_id}/history")
async def get_catalog_product_history(
    salon_id: int,
    kind: Literal["consumable", "equipment"],
    product_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_salon_permission(db, current_user, salon_id, "manage_inventory")
    await _catalog_product_or_404(db, salon_id, kind, product_id)
    target_filter = (
        InventoryMovement.item_id == product_id if kind == "consumable"
        else InventoryMovement.equipment_id == product_id
    )
    movements = (await db.execute(
        select(InventoryMovement)
        .where(target_filter)
        .order_by(InventoryMovement.created_at.desc())
        .limit(100)
    )).scalars().all()
    return [
        {
            "date": movement.created_at.isoformat(),
            "type": movement.type.value,
            "delta": movement.delta,
            "unit_cost": movement.unit_cost_snapshot,
            "unit": product.unit,
            "comment": movement.comment,
        }
        for movement in movements
    ]


@router.post("/audit/{audit_id}/confirm")
async def confirm_audit_api(
    audit_id: int,
    body: Optional[AuditConfirmRequest] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Закрывает завершённый акт инвентаризации."""
    from app.models.models import InventoryAudit

    audit = (await db.execute(select(InventoryAudit).where(InventoryAudit.id == audit_id))).scalar_one_or_none()
    if not audit:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Акт не найден")
    await _authorize_audit(db, audit, current_user)

    try:
        audit = await InventoryService.confirm_audit(
            db,
            audit_id=audit_id,
            actual_quantities=body.actual_quantities if body else None,
            actor=current_user,
        )
    except InventoryError as e:
        raise HTTPException(status_code=e.status, detail=e.message)

    return {"id": audit.id, "status": audit.status.value, "confirmed_at": audit.confirmed_at.isoformat()}


# ========== Мастер: свой мини-склад и списание после клиента (JSON self-service) ==========

@router.get("/my/stock")
async def get_my_stock(
    current_user: User = Depends(require_role(UserRole.MASTER)),
    db: AsyncSession = Depends(get_db),
):
    """Остаток своего мини-склада (для кабинета мастера)."""
    master = (await db.execute(select(Master).where(Master.user_id == current_user.id))).scalar_one_or_none()
    if not master:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Профиль мастера не найден")
    items = await InventoryService.get_master_stock(db, master.id)
    return [
        {"id": i.id, "name": i.name, "unit": i.unit, "quantity": i.quantity}
        for i in items
    ]


class ConsumptionLine(BaseModel):
    item_id: int
    quantity: float


class ConsumptionRequest(BaseModel):
    booking_id: int
    items: list[ConsumptionLine]


@router.post("/my/consumption")
async def log_my_consumption(
    body: ConsumptionRequest,
    current_user: User = Depends(require_role(UserRole.MASTER)),
    db: AsyncSession = Depends(get_db),
):
    """Форма мастера после клиента: сколько расходников фактически потрачено."""
    master = (await db.execute(select(Master).where(Master.user_id == current_user.id))).scalar_one_or_none()
    if not master:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Профиль мастера не найден")

    booking_master_id = (await db.execute(
        select(Booking.master_id).where(Booking.id == body.booking_id)
    )).scalar_one_or_none()
    if booking_master_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Запись не найдена")
    if booking_master_id != master.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Это не ваша запись")

    try:
        booking = await InventoryService.log_consumption(
            db, booking_id=body.booking_id,
            items=[{"item_id": line.item_id, "quantity": line.quantity} for line in body.items],
            actor=current_user,
        )
    except InventoryError as e:
        raise HTTPException(status_code=e.status, detail=e.message)

    return {"booking_id": booking.id, "consumption_reported": booking.consumption_reported}


# ========== Техника и инструменты (общий склад салона, только владелец/админ) ==========

@router.post("/salon/{salon_id}/equipment")
async def add_equipment_web(
    salon_id: int,
    request: Request,
    name: str = Form(...),
    quantity: int = Form(1),
    purchased_at: Optional[str] = Form(None),
    service_life_months: Optional[int] = Form(None),
    cost_per_unit: Optional[int] = Form(None),
    unit: str = Form("шт"),
    min_quantity: float = Form(0),
    db: AsyncSession = Depends(get_db),
):
    """Добавляет позицию техники/инструментов на общий склад салона."""
    from datetime import date as date_cls
    from app.web.auth import get_current_user_from_cookie

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    try:
        await check_salon_permission(db, user, salon_id, "manage_inventory")
    except HTTPException:
        return HTMLResponse(content="Недостаточно прав для управления складом", status_code=403)

    parsed_date = None
    if purchased_at:
        try:
            parsed_date = date_cls.fromisoformat(purchased_at)
        except ValueError:
            pass

    try:
        await InventoryService.add_equipment(
            db, salon_id=salon_id, name=name, quantity=quantity,
            purchased_at=parsed_date, service_life_months=service_life_months, cost_per_unit=cost_per_unit,
            unit=unit, min_quantity=min_quantity, actor=user,
        )
    except InventoryError as e:
        return HTMLResponse(content=e.message, status_code=e.status)

    return RedirectResponse(url="/business/dashboard?tab=warehouse&equipment_added=1", status_code=302)


@router.post("/salon/{salon_id}/equipment/{equipment_id}/toggle")
async def toggle_equipment_web(
    salon_id: int,
    equipment_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Владелец/админ вручную переключает исправно/сломано."""
    await check_salon_permission(db, current_user, salon_id, "manage_inventory")
    try:
        equipment = await InventoryService.toggle_equipment_status(db, equipment_id=equipment_id, salon_id=salon_id)
    except InventoryError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    return {"id": equipment.id, "status": equipment.status.value}


# ========== Заявки: расходник заканчивается / техника сломалась ==========

@router.post("/requests")
async def create_warehouse_request_web(
    request_type: str = Form(...),
    item_id: Optional[int] = Form(None),
    equipment_id: Optional[int] = Form(None),
    comment: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Мастер сигналит: расходник заканчивается, или техника сломалась.
    Доступ — по факту записи Master (не по role, см. has_master_profile)."""
    master = (await db.execute(select(Master).where(Master.user_id == current_user.id))).scalar_one_or_none()
    if master is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="У вас нет профиля мастера")

    try:
        parsed_type = WarehouseRequestType(request_type)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректный тип заявки")

    try:
        req = await InventoryService.create_request(
            db, salon_id=master.salon_id, type=parsed_type, created_by=current_user,
            item_id=item_id, equipment_id=equipment_id, comment=comment,
        )
    except InventoryError as e:
        raise HTTPException(status_code=e.status, detail=e.message)

    await notify_warehouse_request_created(db, req)
    return {"id": req.id, "status": req.status.value}


@router.post("/requests/{request_id}/resolve")
async def resolve_warehouse_request_web(
    request_id: int,
    salon_id: int = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_salon_permission(db, current_user, salon_id, "manage_inventory")
    try:
        req = await InventoryService.resolve_request(db, request_id=request_id, salon_id=salon_id, actor=current_user)
    except InventoryError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    await notify_warehouse_request_resolved(db, req)
    return {"id": req.id, "status": req.status.value}


@router.post("/requests/{request_id}/dismiss")
async def dismiss_warehouse_request_web(
    request_id: int,
    salon_id: int = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_salon_permission(db, current_user, salon_id, "manage_inventory")
    try:
        req = await InventoryService.dismiss_request(db, request_id=request_id, salon_id=salon_id, actor=current_user)
    except InventoryError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    await notify_warehouse_request_resolved(db, req)
    return {"id": req.id, "status": req.status.value}


@router.post("/salon/{salon_id}/notify-toggle")
async def toggle_warehouse_notify_web(
    salon_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Личный тумблер: получать ли Telegram-пуш о заявках склада. Каждый
    участник переключает только свою запись — не общая настройка салона."""
    from app.models.models import SalonMember

    member = (await db.execute(
        select(SalonMember).where(
            SalonMember.salon_id == salon_id,
            SalonMember.user_id == current_user.id,
            SalonMember.is_active == True,
        )
    )).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Вы не участник этого салона")

    member.notify_warehouse_requests = not member.notify_warehouse_requests
    await db.commit()
    return {"notify_warehouse_requests": member.notify_warehouse_requests}
