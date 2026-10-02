from sqlalchemy import select

from app.models.models import (
    Equipment,
    InventoryAuditItem,
    InventoryItem,
    InventoryMovement,
    Master,
    Salon,
    SalonModerationStatus,
    User,
    UserRole,
    WarehouseAssignment,
)
from app.services.inventory_service import InventoryService


async def test_salon_and_master_audits_include_only_their_inventory(db_session):
    async with db_session() as db:
        salon = Salon(
            name="Audit salon",
            address="Test street",
            phone="+70000000101",
            latitude=1.0,
            longitude=1.0,
            timezone="Europe/Moscow",
            moderation_status=SalonModerationStatus.APPROVED,
            is_active=True,
        )
        actor = User(
            phone="+70000000102",
            full_name="Audit manager",
            hashed_password="x",
            role=UserRole.BUSINESS,
        )
        masters_users = [
            User(phone="+70000000103", full_name="Audit master 1", hashed_password="x", role=UserRole.MASTER),
            User(phone="+70000000104", full_name="Audit master 2", hashed_password="x", role=UserRole.MASTER),
        ]
        db.add_all([salon, actor, *masters_users])
        await db.flush()
        masters = [
            Master(user_id=user.id, salon_id=salon.id, specialization="Test")
            for user in masters_users
        ]
        db.add_all(masters)
        await db.flush()

        assigned_items = [
            InventoryItem(
                salon_id=salon.id,
                name=f"Master consumable {i}",
                unit="шт",
                quantity=10,
                cost_per_unit=100,
                min_quantity=1,
            )
            for i in (1, 2)
        ]
        assigned_equipment = [
            Equipment(
                salon_id=salon.id,
                name=f"Master equipment {i}",
                quantity=1,
                unit="шт",
                min_quantity=0,
                cost_per_unit=500,
            )
            for i in (1, 2)
        ]
        db.add_all([*assigned_items, *assigned_equipment])
        await db.flush()
        db.add_all([
            WarehouseAssignment(inventory_item_id=assigned_items[0].id, master_id=masters[0].id),
            WarehouseAssignment(inventory_item_id=assigned_items[1].id, master_id=masters[1].id),
            WarehouseAssignment(equipment_id=assigned_equipment[0].id, master_id=masters[0].id),
            WarehouseAssignment(equipment_id=assigned_equipment[1].id, master_id=masters[1].id),
        ])
        await db.commit()

        salon_audit = await InventoryService.start_audit(db, salon_id=salon.id, actor=actor)
        master_audit = await InventoryService.start_audit(
            db, salon_id=salon.id, master_id=masters[0].id, actor=masters_users[0]
        )
        salon_rows = (await db.execute(
            select(InventoryAuditItem).where(InventoryAuditItem.audit_id == salon_audit.id)
        )).scalars().all()
        master_rows = (await db.execute(
            select(InventoryAuditItem).where(InventoryAuditItem.audit_id == master_audit.id)
        )).scalars().all()

        assert len(salon_rows) == 4
        assert {row.item_id for row in master_rows if row.item_id is not None} == {assigned_items[0].id}
        assert {row.equipment_id for row in master_rows if row.equipment_id is not None} == {
            assigned_equipment[0].id
        }


async def test_audit_adjusts_and_archives_after_each_card_is_reviewed(db_session):
    async with db_session() as db:
        salon = Salon(
            name="Audit action salon",
            address="Test street",
            phone="+70000000111",
            latitude=1.0,
            longitude=1.0,
            timezone="Europe/Moscow",
            moderation_status=SalonModerationStatus.APPROVED,
            is_active=True,
        )
        actor = User(
            phone="+70000000112",
            full_name="Audit manager",
            hashed_password="x",
            role=UserRole.BUSINESS,
        )
        db.add_all([salon, actor])
        await db.flush()
        products = [
            InventoryItem(
                salon_id=salon.id,
                name="Count adjustment",
                unit="шт",
                quantity=10,
                cost_per_unit=100,
                min_quantity=2,
            ),
            InventoryItem(
                salon_id=salon.id,
                name="Archived stock",
                unit="шт",
                quantity=3,
                cost_per_unit=100,
                min_quantity=1,
            ),
            InventoryItem(
                salon_id=salon.id,
                name="Correct stock",
                unit="шт",
                quantity=8,
                cost_per_unit=100,
                min_quantity=1,
            ),
        ]
        db.add_all(products)
        await db.commit()

        audit = await InventoryService.start_audit(db, salon_id=salon.id, actor=actor)
        rows = (await db.execute(
            select(InventoryAuditItem)
            .where(InventoryAuditItem.audit_id == audit.id)
        )).scalars().all()
        rows_by_item = {row.item_id: row for row in rows}
        decisions = (
            (products[0], "adjust", 7),
            (products[1], "archive", None),
            (products[2], "correct", None),
        )
        for product, action, quantity in decisions:
            await InventoryService.review_audit_item(
                db,
                audit_id=audit.id,
                audit_item_id=rows_by_item[product.id].id,
                action=action,
                actual_quantity=quantity,
            )

        await InventoryService.confirm_audit(db, audit_id=audit.id, actor=actor)
        await db.refresh(products[0])
        await db.refresh(products[1])
        await db.refresh(products[2])
        movements = (await db.execute(
            select(InventoryMovement).where(InventoryMovement.item_id == products[0].id)
        )).scalars().all()

        assert products[0].quantity == 7
        assert products[1].is_active is False
        assert products[2].quantity == 8
        assert len(movements) == 1
        assert movements[0].delta == -3
