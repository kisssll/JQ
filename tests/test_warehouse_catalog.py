from types import SimpleNamespace

from app.models.models import EquipmentStatus
from app.models.models import (
    InventoryItem,
    Master,
    Salon,
    SalonModerationStatus,
    Service,
    User,
    UserRole,
    WarehouseAssignment,
)
from app.services.inventory_service import InventoryService
from app.web.pages.business.tabs.warehouse import _equipment_condition_counts
from app.web.pages.business.tabs.warehouse_catalog import _catalog_state


def test_equipment_status_uses_condition_not_restock_threshold():
    working_hair_dryer = SimpleNamespace(
        is_active=True,
        status=EquipmentStatus.WORKING,
        quantity=5,
        min_quantity=5,
    )
    broken_hair_dryer = SimpleNamespace(
        is_active=True,
        status=EquipmentStatus.BROKEN,
        quantity=5,
        min_quantity=5,
    )
    lost_hair_dryer = SimpleNamespace(
        is_active=True,
        status=EquipmentStatus.LOST,
        quantity=5,
        min_quantity=5,
    )

    assert _catalog_state(working_hair_dryer, "equipment") == ("ok", "Всё в порядке")
    assert _catalog_state(broken_hair_dryer, "equipment") == ("broken", "Сломано: 5")
    assert _catalog_state(lost_hair_dryer, "equipment") == ("lost", "Утеряно: 5")


def test_consumables_still_use_minimum_stock_threshold():
    low_stock = SimpleNamespace(is_active=True, quantity=5, min_quantity=5)

    assert _catalog_state(low_stock, "consumable") == ("low", "Нужно пополнить")


def test_equipment_condition_counter_sums_broken_and_lost_units_only():
    equipment = [
        SimpleNamespace(is_active=True, status=EquipmentStatus.BROKEN, quantity=2),
        SimpleNamespace(is_active=True, status=EquipmentStatus.LOST, quantity=1),
        SimpleNamespace(is_active=True, status=EquipmentStatus.WORKING, quantity=5),
        SimpleNamespace(is_active=False, status=EquipmentStatus.BROKEN, quantity=4),
    ]

    assert _equipment_condition_counts(equipment) == (2, 1)


async def test_shared_and_service_assigned_stock_is_visible_to_eligible_masters(db_session):
    async with db_session() as db:
        salon = Salon(
            name="Warehouse test salon",
            address="Test street",
            phone="+70000000001",
            latitude=1.0,
            longitude=1.0,
            timezone="Europe/Moscow",
            moderation_status=SalonModerationStatus.APPROVED,
            is_active=True,
        )
        master_users = [
            User(phone="+70000000002", full_name="Master One", hashed_password="x", role=UserRole.MASTER),
            User(phone="+70000000003", full_name="Master Two", hashed_password="x", role=UserRole.MASTER),
        ]
        db.add_all([salon, *master_users])
        await db.flush()

        masters = [
            Master(user_id=user.id, salon_id=salon.id, specialization="Test")
            for user in master_users
        ]
        db.add_all(masters)
        await db.flush()
        service = Service(
            master_id=masters[0].id,
            assigned_masters=[masters[1]],
            name="Nail service",
            price=1000,
            duration_minutes=60,
        )
        db.add(service)
        await db.flush()

        shared_item = InventoryItem(
            salon_id=salon.id,
            name="Shared polish",
            unit="ml",
            quantity=20,
            cost_per_unit=10,
            min_quantity=5,
        )
        service_item = InventoryItem(
            salon_id=salon.id,
            name="Service polish",
            unit="ml",
            quantity=12,
            cost_per_unit=15,
            min_quantity=3,
        )
        db.add_all([shared_item, service_item])
        await db.flush()
        db.add_all([
            WarehouseAssignment(inventory_item_id=shared_item.id, master_id=masters[0].id),
            WarehouseAssignment(inventory_item_id=shared_item.id, master_id=masters[1].id),
            WarehouseAssignment(inventory_item_id=service_item.id, service_id=service.id),
        ])
        await db.commit()

        first_master_stock = await InventoryService.get_master_stock(db, masters[0].id)
        second_master_stock = await InventoryService.get_master_stock(db, masters[1].id)

        assert {item.id for item in first_master_stock} == {shared_item.id, service_item.id}
        assert {item.id for item in second_master_stock} == {shared_item.id, service_item.id}
        assert next(item for item in first_master_stock if item.id == shared_item.id).quantity == 20
        assert next(item for item in second_master_stock if item.id == shared_item.id).quantity == 20
