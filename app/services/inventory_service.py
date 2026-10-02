# app/services/inventory_service.py
"""Складской учёт: общий каталог с остатками, назначаемыми мастерам и услугам.

Единый источник истины — InventoryMovement (журнал движений). Остаток
InventoryItem.quantity денормализован для быстрых выборок и обновляется
только через методы этого сервиса, никогда напрямую.
"""
from __future__ import annotations

from datetime import datetime
import math
from typing import Optional

from sqlalchemy import select, or_
from sqlalchemy.sql import func as sql_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    InventoryItem, InventoryMovement, InventoryMovementType,
    InventoryAudit, InventoryAuditItem, InventoryAuditStatus,
    Booking, BookingStatus, Master,
    Equipment, EquipmentStatus, WarehouseAssignment, WarehouseRequest, WarehouseRequestType,
    WarehouseRequestStatus, Service,
)


class InventoryError(Exception):
    """Бизнес-ошибка склада. message — текст для пользователя, status — HTTP-код."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class InventoryService:
    @staticmethod
    async def notify_if_low_stock_transition(
        db: AsyncSession, *, salon_id: int, name: str, unit: str, old_quantity: float,
        old_min_quantity: float, quantity: float, min_quantity: float,
    ) -> None:
        if old_quantity > old_min_quantity and quantity <= min_quantity:
            from app.services.notifications import notify_warehouse_low_stock

            await notify_warehouse_low_stock(
                db, salon_id=salon_id, item_name=name, quantity=quantity, unit=unit,
                min_quantity=min_quantity,
            )

    @staticmethod
    async def get_master_stock(db: AsyncSession, master_id: int) -> list[InventoryItem]:
        """Active consumables assigned to a master, their services, or the salon."""
        master_row = (await db.execute(
            select(Master.id, Master.salon_id).where(Master.id == master_id)
        )).one_or_none()
        if master_row is None:
            return []
        _, salon_id = master_row

        items = list((await db.execute(
            select(InventoryItem)
            .where(InventoryItem.salon_id == salon_id, InventoryItem.is_active == True)
            .order_by(InventoryItem.name)
        )).scalars().all())
        if not items:
            return []

        item_ids = [item.id for item in items]
        assignments = (await db.execute(
            select(WarehouseAssignment).where(WarehouseAssignment.inventory_item_id.in_(item_ids))
        )).scalars().all()
        assignments_by_item: dict[int, list[WarehouseAssignment]] = {}
        for assignment in assignments:
            assignments_by_item.setdefault(assignment.inventory_item_id, []).append(assignment)

        service_ids = set((await db.execute(
            select(Service.id).where(or_(
                Service.master_id == master_id,
                Service.assigned_masters.any(Master.id == master_id),
            ))
        )).scalars().all())

        visible = []
        for item in items:
            item_assignments = assignments_by_item.get(item.id, [])
            if not item_assignments:
                if item.master_id is None or item.master_id == master_id:
                    visible.append(item)
                continue
            if any(a.master_id == master_id or a.service_id in service_ids for a in item_assignments):
                visible.append(item)
        return visible

    @staticmethod
    async def receive_stock(
        db: AsyncSession, *, item_id: int, quantity: float, comment: str, actor,
    ) -> InventoryItem:
        """Приход (закупка): увеличивает остаток позиции."""
        if quantity <= 0:
            raise InventoryError("Количество прихода должно быть положительным")

        item = (await db.execute(select(InventoryItem).where(InventoryItem.id == item_id))).scalar_one_or_none()
        if not item:
            raise InventoryError("Позиция склада не найдена", status=404)

        old_quantity = item.quantity
        db.add(InventoryMovement(
            item_id=item.id,
            type=InventoryMovementType.RECEIPT,
            delta=quantity,
            unit_cost_snapshot=item.cost_per_unit,
            created_by_id=actor.id,
            comment=comment or None,
        ))
        item.quantity += quantity
        await db.commit()
        await db.refresh(item)
        await InventoryService.notify_if_low_stock_transition(
            db, salon_id=item.salon_id, name=item.name, unit=item.unit,
            old_quantity=old_quantity, old_min_quantity=item.min_quantity,
            quantity=item.quantity, min_quantity=item.min_quantity,
        )
        return item

    @staticmethod
    async def log_consumption(
        db: AsyncSession, *, booking_id: int, items: list[dict], actor,
    ) -> Booking:
        """Форма мастера после клиента: списывает фактически потраченные
        расходники по завершённой записи. `items` — [{"item_id": int, "quantity": float}, ...]."""
        if not items:
            raise InventoryError("Укажите хотя бы одну потраченную позицию")

        booking = (await db.execute(select(Booking).where(Booking.id == booking_id))).scalar_one_or_none()
        if not booking:
            raise InventoryError("Запись не найдена", status=404)
        if booking.status != BookingStatus.COMPLETED:
            raise InventoryError("Списать расходники можно только по завершённой записи")
        if booking.consumption_reported:
            raise InventoryError("По этой записи расходники уже списаны", status=409)

        # Валидируем всё до применения — чтобы не списать часть позиций,
        # упершись в нехватку остатка на середине списка.
        resolved: list[tuple[InventoryItem, float]] = []
        for line in items:
            quantity = float(line.get("quantity") or 0)
            if quantity <= 0:
                raise InventoryError("Количество должно быть положительным")
            item = (await db.execute(
                select(InventoryItem).where(InventoryItem.id == line.get("item_id"))
            )).scalar_one_or_none()
            if not item:
                raise InventoryError("Позиция склада не найдена", status=404)
            master = (await db.execute(select(Master).where(Master.id == booking.master_id))).scalar_one()
            if item.salon_id != master.salon_id:
                raise InventoryError("Позиция склада принадлежит другому мастеру", status=403)
            assignments = (await db.execute(
                select(WarehouseAssignment).where(WarehouseAssignment.inventory_item_id == item.id)
            )).scalars().all()
            if assignments:
                if not any(
                    assignment.master_id == booking.master_id or assignment.service_id == booking.service_id
                    for assignment in assignments
                ):
                    raise InventoryError("Позиция не назначена этому мастеру или услуге", status=403)
            elif item.master_id is not None and item.master_id != booking.master_id:
                raise InventoryError("Позиция склада принадлежит другому мастеру", status=403)
            if item.quantity < quantity:
                raise InventoryError(f"Недостаточно «{item.name}» на складе: остаток {item.quantity} {item.unit}")
            resolved.append((item, quantity))

        previous_quantities = {item.id: item.quantity for item, _quantity in resolved}
        for item, quantity in resolved:
            db.add(InventoryMovement(
                item_id=item.id,
                type=InventoryMovementType.CONSUMPTION,
                delta=-quantity,
                unit_cost_snapshot=item.cost_per_unit,
                booking_id=booking.id,
                created_by_id=actor.id,
            ))
            item.quantity -= quantity

        booking.consumption_reported = True
        await db.commit()
        await db.refresh(booking)
        for item, _quantity in resolved:
            await InventoryService.notify_if_low_stock_transition(
                db, salon_id=item.salon_id, name=item.name, unit=item.unit,
                old_quantity=previous_quantities[item.id], old_min_quantity=item.min_quantity,
                quantity=item.quantity, min_quantity=item.min_quantity,
            )
        return booking

    @staticmethod
    async def start_audit(
        db: AsyncSession, *, salon_id: int, actor, master_id: Optional[int] = None,
    ) -> InventoryAudit:
        """Открывает акт для мастера либо для всего салона."""
        audit_scope = InventoryAudit.master_id.is_(None) if master_id is None else InventoryAudit.master_id == master_id
        open_audit = (await db.execute(
            select(InventoryAudit).where(
                InventoryAudit.salon_id == salon_id,
                audit_scope,
                InventoryAudit.status == InventoryAuditStatus.DRAFT,
            )
        )).scalar_one_or_none()
        if open_audit:
            raise InventoryError("Для этого склада уже открыта инвентаризация", status=409)

        if master_id is None:
            items = list((await db.execute(
                select(InventoryItem).where(
                    InventoryItem.salon_id == salon_id,
                    InventoryItem.is_active == True,
                ).order_by(InventoryItem.name)
            )).scalars().all())
            equipment = list((await db.execute(
                select(Equipment).where(
                    Equipment.salon_id == salon_id,
                    Equipment.is_active == True,
                ).order_by(Equipment.name)
            )).scalars().all())
        else:
            items = await InventoryService.get_master_stock(db, master_id)
            equipment = await InventoryService.get_salon_equipment(db, salon_id, master_id)

        if not items and not equipment:
            raise InventoryError("На складе нет активных позиций для пересчёта")

        audit = InventoryAudit(
            salon_id=salon_id,
            master_id=master_id,
            status=InventoryAuditStatus.DRAFT,
            created_by_id=actor.id,
        )
        db.add(audit)
        await db.flush()

        for item in items:
            db.add(InventoryAuditItem(audit_id=audit.id, item_id=item.id, expected_quantity=item.quantity))
        for row in equipment:
            db.add(InventoryAuditItem(
                audit_id=audit.id,
                equipment_id=row.id,
                expected_quantity=row.quantity,
            ))

        await db.commit()
        await db.refresh(audit)
        return audit

    @staticmethod
    async def review_audit_item(
        db: AsyncSession, *, audit_id: int, audit_item_id: int, action: str,
        actual_quantity: Optional[float] = None,
    ) -> InventoryAuditItem:
        """Сохраняет решение по карточке, не меняя склад до завершения акта."""
        audit = (await db.execute(
            select(InventoryAudit).where(InventoryAudit.id == audit_id).with_for_update()
        )).scalar_one_or_none()
        if not audit:
            raise InventoryError("Акт инвентаризации не найден", status=404)
        if audit.status != InventoryAuditStatus.DRAFT:
            raise InventoryError("Акт уже закрыт", status=409)

        audit_item = (await db.execute(
            select(InventoryAuditItem).where(
                InventoryAuditItem.id == audit_item_id,
                InventoryAuditItem.audit_id == audit_id,
            )
        )).scalar_one_or_none()
        if not audit_item:
            raise InventoryError("Позиция не найдена в этом акте", status=404)

        if action == "correct":
            audit_item.actual_quantity = audit_item.expected_quantity
            audit_item.is_adjusted = False
            audit_item.is_archived = False
        elif action == "adjust":
            if actual_quantity is None or not math.isfinite(actual_quantity) or actual_quantity < 0:
                raise InventoryError("Укажите фактическое количество не меньше нуля")
            audit_item.actual_quantity = actual_quantity
            audit_item.is_adjusted = True
            audit_item.is_archived = False
        elif action == "archive":
            audit_item.actual_quantity = None
            audit_item.is_adjusted = False
            audit_item.is_archived = True
        else:
            raise InventoryError("Неизвестное действие с позицией")

        audit_item.is_reviewed = True
        await db.commit()
        await db.refresh(audit_item)
        return audit_item

    @staticmethod
    async def confirm_audit(
        db: AsyncSession, *, audit_id: int, actor,
        actual_quantities: Optional[dict[int, float]] = None,
    ) -> InventoryAudit:
        """Закрывает акт и применяет все отмеченные изменения атомарно."""
        audit = (await db.execute(
            select(InventoryAudit).where(InventoryAudit.id == audit_id).with_for_update()
        )).scalar_one_or_none()
        if not audit:
            raise InventoryError("Акт инвентаризации не найден", status=404)
        if audit.status != InventoryAuditStatus.DRAFT:
            raise InventoryError("Акт уже закрыт")

        audit_items = (await db.execute(
            select(InventoryAuditItem).where(InventoryAuditItem.audit_id == audit_id)
        )).scalars().all()

        for audit_item in audit_items:
            if (
                not audit_item.is_reviewed
                and actual_quantities is not None
                and audit_item.item_id is not None
                and audit_item.item_id in actual_quantities
            ):
                actual = float(actual_quantities[audit_item.item_id])
                if not math.isfinite(actual) or actual < 0:
                    raise InventoryError("Остаток не может быть отрицательным")
                audit_item.actual_quantity = actual
                audit_item.is_adjusted = True
                audit_item.is_reviewed = True
            if not audit_item.is_reviewed:
                raise InventoryError("Сначала проверьте каждую позицию инвентаризации")

        low_stock_changes = []
        for audit_item in audit_items:
            if audit_item.item_id is not None:
                product = (await db.execute(
                    select(InventoryItem).where(InventoryItem.id == audit_item.item_id)
                )).scalar_one_or_none()
                if product is None:
                    raise InventoryError("Позиция склада больше не существует", status=409)
            else:
                product = (await db.execute(
                    select(Equipment).where(Equipment.id == audit_item.equipment_id)
                )).scalar_one_or_none()
                if product is None:
                    raise InventoryError("Позиция техники больше не существует", status=409)

            if audit_item.is_archived:
                product.is_active = False
                continue
            if not audit_item.is_adjusted:
                continue

            actual = audit_item.actual_quantity
            if actual is None:
                raise InventoryError("Для проверенной позиции не сохранено фактическое количество")
            old_quantity = product.quantity
            diff = actual - old_quantity
            if diff != 0:
                db.add(InventoryMovement(
                    item_id=product.id if audit_item.item_id is not None else None,
                    equipment_id=product.id if audit_item.equipment_id is not None else None,
                    type=InventoryMovementType.ADJUSTMENT,
                    delta=diff,
                    unit_cost_snapshot=product.cost_per_unit or 0,
                    created_by_id=actor.id,
                    comment=f"Инвентаризация #{audit.id}",
                ))
                product.quantity = actual
                if audit_item.item_id is not None:
                    low_stock_changes.append((product, old_quantity))

        audit.status = InventoryAuditStatus.CONFIRMED
        audit.confirmed_at = sql_func.now()  # серверное время БД: naive now() поехал бы при смене TZ контейнера
        await db.commit()
        await db.refresh(audit)
        for item, old_quantity in low_stock_changes:
            await InventoryService.notify_if_low_stock_transition(
                db, salon_id=item.salon_id, name=item.name, unit=item.unit,
                old_quantity=old_quantity, old_min_quantity=item.min_quantity,
                quantity=item.quantity, min_quantity=item.min_quantity,
            )
        return audit

    # ========== Техника и инструменты (общий склад салона) ==========

    @staticmethod
    async def get_salon_equipment(
        db: AsyncSession, salon_id: int, master_id: Optional[int] = None,
    ) -> list[Equipment]:
        return await InventoryService._get_salon_equipment(db, salon_id, master_id)

    @staticmethod
    async def _get_salon_equipment(
        db: AsyncSession, salon_id: int, master_id: Optional[int] = None,
    ) -> list[Equipment]:
        result = await db.execute(
            select(Equipment)
            .where(Equipment.salon_id == salon_id, Equipment.is_active == True)
            .order_by(Equipment.name)
        )
        equipment = list(result.scalars().all())
        if master_id is None or not equipment:
            return equipment

        equipment_ids = [row.id for row in equipment]
        assignments = (await db.execute(
            select(WarehouseAssignment).where(WarehouseAssignment.equipment_id.in_(equipment_ids))
        )).scalars().all()
        assignments_by_equipment: dict[int, list[WarehouseAssignment]] = {}
        for assignment in assignments:
            assignments_by_equipment.setdefault(assignment.equipment_id, []).append(assignment)
        service_ids = set((await db.execute(
            select(Service.id).where(or_(
                Service.master_id == master_id,
                Service.assigned_masters.any(Master.id == master_id),
            ))
        )).scalars().all())

        return [
            row for row in equipment
            if not assignments_by_equipment.get(row.id)
            or any(
                a.master_id == master_id or a.service_id in service_ids
                for a in assignments_by_equipment[row.id]
            )
        ]

    @staticmethod
    async def add_equipment(
        db: AsyncSession, *, salon_id: int, name: str, quantity: float,
        purchased_at=None, service_life_months: Optional[int] = None, cost_per_unit: Optional[int] = None,
        unit: str = "шт", min_quantity: float = 0, master_ids: Optional[list[int]] = None,
        service_ids: Optional[list[int]] = None, actor=None,
    ) -> Equipment:
        if quantity <= 0:
            raise InventoryError("Количество должно быть положительным")
        master_ids = list(dict.fromkeys(master_ids or []))
        service_ids = list(dict.fromkeys(service_ids or []))
        if master_ids and service_ids:
            raise InventoryError("Выберите мастеров или услуги, но не оба варианта")
        salon_master_ids = set((await db.execute(
            select(Master.id).where(Master.salon_id == salon_id)
        )).scalars().all())
        if not set(master_ids).issubset(salon_master_ids):
            raise InventoryError("Один или несколько мастеров не относятся к этому салону")
        if service_ids:
            service_master_ids = set((await db.execute(
                select(Service.master_id).where(Service.id.in_(service_ids))
            )).scalars().all())
            if not service_master_ids.issubset(salon_master_ids) or len(service_ids) != len(
                (await db.execute(select(Service.id).where(Service.id.in_(service_ids)))).scalars().all()
            ):
                raise InventoryError("Одна или несколько услуг не относятся к этому салону")
        equipment = Equipment(
            salon_id=salon_id, name=name, quantity=quantity,
            unit=unit, min_quantity=min_quantity,
            purchased_at=purchased_at, service_life_months=service_life_months, cost_per_unit=cost_per_unit,
        )
        db.add(equipment)
        await db.flush()
        for master_id in master_ids:
            db.add(WarehouseAssignment(equipment_id=equipment.id, master_id=master_id))
        for service_id in service_ids:
            db.add(WarehouseAssignment(equipment_id=equipment.id, service_id=service_id))
        if actor is not None:
            db.add(InventoryMovement(
                equipment_id=equipment.id,
                type=InventoryMovementType.RECEIPT,
                delta=quantity,
                unit_cost_snapshot=cost_per_unit or 0,
                created_by_id=actor.id,
                comment="Первоначальный остаток",
            ))
        await db.commit()
        await db.refresh(equipment)
        return equipment

    @staticmethod
    async def toggle_equipment_status(db: AsyncSession, *, equipment_id: int, salon_id: int) -> Equipment:
        equipment = (await db.execute(
            select(Equipment).where(Equipment.id == equipment_id, Equipment.salon_id == salon_id)
        )).scalar_one_or_none()
        if not equipment:
            raise InventoryError("Позиция техники не найдена", status=404)
        equipment.status = (
            EquipmentStatus.BROKEN if equipment.status == EquipmentStatus.WORKING else EquipmentStatus.WORKING
        )
        await db.commit()
        await db.refresh(equipment)
        return equipment

    # ========== Заявки: расходник заканчивается / техника сломалась ==========

    @staticmethod
    async def create_request(
        db: AsyncSession, *, salon_id: int, type: WarehouseRequestType, created_by,
        item_id: Optional[int] = None, equipment_id: Optional[int] = None, comment: str = "",
    ) -> WarehouseRequest:
        if type == WarehouseRequestType.CONSUMABLE_LOW:
            if not item_id:
                raise InventoryError("Не указана позиция расходника")
            item = (await db.execute(select(InventoryItem).where(InventoryItem.id == item_id))).scalar_one_or_none()
            if not item:
                raise InventoryError("Позиция склада не найдена", status=404)
            master = (await db.execute(select(Master).where(Master.id == item.master_id))).scalar_one_or_none()
            if not master or master.salon_id != salon_id:
                raise InventoryError("Позиция принадлежит другому салону", status=403)
            equipment_id = None
        else:
            if not equipment_id:
                raise InventoryError("Не указана позиция техники")
            equipment = (await db.execute(select(Equipment).where(Equipment.id == equipment_id))).scalar_one_or_none()
            if not equipment or equipment.salon_id != salon_id:
                raise InventoryError("Техника не найдена в этом салоне", status=404)
            item_id = None

        request = WarehouseRequest(
            salon_id=salon_id, type=type, item_id=item_id, equipment_id=equipment_id,
            created_by_id=created_by.id, comment=comment or None,
        )
        db.add(request)
        await db.commit()
        await db.refresh(request)
        return request

    @staticmethod
    async def get_pending_requests(db: AsyncSession, salon_id: int) -> list[WarehouseRequest]:
        result = await db.execute(
            select(WarehouseRequest)
            .where(WarehouseRequest.salon_id == salon_id, WarehouseRequest.status == WarehouseRequestStatus.PENDING)
            .order_by(WarehouseRequest.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def _resolve_or_dismiss(
        db: AsyncSession, *, request_id: int, salon_id: int, actor, new_status: WarehouseRequestStatus,
    ) -> WarehouseRequest:
        request = (await db.execute(
            select(WarehouseRequest).where(WarehouseRequest.id == request_id, WarehouseRequest.salon_id == salon_id)
        )).scalar_one_or_none()
        if not request:
            raise InventoryError("Заявка не найдена", status=404)
        if request.status != WarehouseRequestStatus.PENDING:
            raise InventoryError("Заявка уже обработана", status=409)

        request.status = new_status
        request.resolved_by_id = actor.id
        request.resolved_at = sql_func.now()  # серверное время БД, см. confirmed_at
        await db.commit()
        await db.refresh(request)
        return request

    @staticmethod
    async def resolve_request(db: AsyncSession, *, request_id: int, salon_id: int, actor) -> WarehouseRequest:
        return await InventoryService._resolve_or_dismiss(
            db, request_id=request_id, salon_id=salon_id, actor=actor, new_status=WarehouseRequestStatus.RESOLVED,
        )

    @staticmethod
    async def dismiss_request(db: AsyncSession, *, request_id: int, salon_id: int, actor) -> WarehouseRequest:
        return await InventoryService._resolve_or_dismiss(
            db, request_id=request_id, salon_id=salon_id, actor=actor, new_status=WarehouseRequestStatus.DISMISSED,
        )

    @staticmethod
    async def unreported_bookings(db: AsyncSession, salon_id: int) -> list[Booking]:
        """Завершённые визиты без списания расходников — для напоминания админу."""
        master_ids_result = await db.execute(select(Master.id).where(Master.salon_id == salon_id))
        master_ids = [row[0] for row in master_ids_result.all()]
        if not master_ids:
            return []
        result = await db.execute(
            select(Booking).where(
                Booking.master_id.in_(master_ids),
                Booking.status == BookingStatus.COMPLETED,
                Booking.consumption_reported == False,
            ).order_by(Booking.start_time.desc())
        )
        return list(result.scalars().all())
