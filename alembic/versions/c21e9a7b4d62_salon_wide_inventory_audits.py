"""support salon-wide and sequential inventory audits

Revision ID: c21e9a7b4d62
Revises: 9a2c7e4d1f60
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c21e9a7b4d62"
down_revision: Union[str, Sequence[str], None] = "9a2c7e4d1f60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("inventory_audits", sa.Column("salon_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE inventory_audits AS a SET salon_id = m.salon_id "
        "FROM masters AS m WHERE a.master_id = m.id"
    )
    op.alter_column("inventory_audits", "salon_id", nullable=False)
    op.alter_column("inventory_audits", "master_id", existing_type=sa.Integer(), nullable=True)
    op.create_foreign_key(
        "inventory_audits_salon_id_fkey",
        "inventory_audits",
        "salons",
        ["salon_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.alter_column("inventory_audit_items", "item_id", existing_type=sa.Integer(), nullable=True)
    op.add_column(
        "inventory_audit_items",
        sa.Column("equipment_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "inventory_audit_items_equipment_id_fkey",
        "inventory_audit_items",
        "equipment",
        ["equipment_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.add_column(
        "inventory_audit_items",
        sa.Column("is_reviewed", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "inventory_audit_items",
        sa.Column("is_adjusted", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "inventory_audit_items",
        sa.Column("is_archived", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_check_constraint(
        "check_inventory_audit_item_one_product",
        "inventory_audit_items",
        "(item_id IS NOT NULL) != (equipment_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "check_inventory_audit_item_one_product",
        "inventory_audit_items",
        type_="check",
    )
    op.execute("DELETE FROM inventory_audit_items WHERE equipment_id IS NOT NULL")
    op.drop_column("inventory_audit_items", "is_archived")
    op.drop_column("inventory_audit_items", "is_adjusted")
    op.drop_column("inventory_audit_items", "is_reviewed")
    op.drop_constraint(
        "inventory_audit_items_equipment_id_fkey",
        "inventory_audit_items",
        type_="foreignkey",
    )
    op.drop_column("inventory_audit_items", "equipment_id")
    op.alter_column("inventory_audit_items", "item_id", existing_type=sa.Integer(), nullable=False)

    op.execute("DELETE FROM inventory_audits WHERE master_id IS NULL")
    op.drop_constraint(
        "inventory_audits_salon_id_fkey",
        "inventory_audits",
        type_="foreignkey",
    )
    op.drop_column("inventory_audits", "salon_id")
    op.alter_column("inventory_audits", "master_id", existing_type=sa.Integer(), nullable=False)
