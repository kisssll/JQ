"""unified warehouse catalog and assignments

Revision ID: 9a2c7e4d1f60
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9a2c7e4d1f60"
down_revision: Union[str, Sequence[str], None] = (
    "a3b4c5d6e7f8",
    "a3f5d2c81b40",
    "c4f8a1e6b207",
    "c8d9e0f1a2b3",
    "c9e1a2b3d4f5",
    "d4e5f6a7b8c0",
    "d4e5f6a7b8c9",
    "e1c2a3b4d5f6",
    "e1f2a3b4c5d6",
    "fe484a8f7254",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("inventory_items", sa.Column("salon_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE inventory_items AS i SET salon_id = m.salon_id "
        "FROM masters AS m WHERE i.master_id = m.id"
    )
    op.alter_column("inventory_items", "salon_id", nullable=False)
    op.alter_column("inventory_items", "master_id", existing_type=sa.Integer(), nullable=True)
    op.drop_constraint("inventory_items_master_id_fkey", "inventory_items", type_="foreignkey")
    op.create_foreign_key(
        "inventory_items_master_id_fkey",
        "inventory_items",
        "masters",
        ["master_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("equipment", sa.Column("unit", sa.String(length=20), server_default="шт", nullable=False))
    op.add_column("equipment", sa.Column("min_quantity", sa.Float(), server_default="0", nullable=False))
    op.alter_column(
        "equipment",
        "quantity",
        existing_type=sa.Integer(),
        type_=sa.Float(),
        postgresql_using="quantity::double precision",
    )

    op.alter_column("inventory_movements", "item_id", existing_type=sa.Integer(), nullable=True)
    op.add_column("inventory_movements", sa.Column("equipment_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "inventory_movements_equipment_id_fkey",
        "inventory_movements",
        "equipment",
        ["equipment_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "check_inventory_movement_one_target",
        "inventory_movements",
        "(item_id IS NOT NULL) != (equipment_id IS NOT NULL)",
    )

    op.create_table(
        "warehouse_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("inventory_item_id", sa.Integer(), nullable=True),
        sa.Column("equipment_id", sa.Integer(), nullable=True),
        sa.Column("master_id", sa.Integer(), nullable=True),
        sa.Column("service_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "(inventory_item_id IS NOT NULL) != (equipment_id IS NOT NULL)",
            name="check_warehouse_assignment_one_product",
        ),
        sa.CheckConstraint(
            "(master_id IS NOT NULL) != (service_id IS NOT NULL)",
            name="check_warehouse_assignment_one_target",
        ),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["equipment_id"], ["equipment.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["master_id"], ["masters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_warehouse_assignments_inventory_item",
        "warehouse_assignments",
        ["inventory_item_id"],
    )
    op.create_index(
        "ix_warehouse_assignments_equipment",
        "warehouse_assignments",
        ["equipment_id"],
    )
    op.execute(
        "INSERT INTO warehouse_assignments (inventory_item_id, master_id) "
        "SELECT id, master_id FROM inventory_items WHERE master_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_table("warehouse_assignments")
    op.drop_constraint(
        "check_inventory_movement_one_target",
        "inventory_movements",
        type_="check",
    )
    op.drop_constraint(
        "inventory_movements_equipment_id_fkey",
        "inventory_movements",
        type_="foreignkey",
    )
    op.drop_column("inventory_movements", "equipment_id")
    op.alter_column("inventory_movements", "item_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("equipment", "quantity", existing_type=sa.Float(), type_=sa.Integer())
    op.drop_column("equipment", "min_quantity")
    op.drop_column("equipment", "unit")
    op.drop_constraint("inventory_items_master_id_fkey", "inventory_items", type_="foreignkey")
    op.create_foreign_key(
        "inventory_items_master_id_fkey",
        "inventory_items",
        "masters",
        ["master_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("inventory_items", "master_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("inventory_items", "salon_id")
