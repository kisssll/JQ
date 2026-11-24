"""Add sport coach schedule, services and individual booking fields.

Revision ID: c824e9f3b1a2
Revises: b713c9d2a4e1
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op


revision: str = "c824e9f3b1a2"
down_revision: Union[str, Sequence[str], None] = "b713c9d2a4e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. sport_coach_schedules
    op.create_table(
        "sport_coach_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "coach_id",
            sa.Integer(),
            sa.ForeignKey("sport_coaches.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("slot_duration_minutes", sa.Integer(), server_default="60", nullable=False),
        sa.Column("break_minutes", sa.Integer(), server_default="15", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
    )

    # 2. sport_services
    op.create_table(
        "sport_services",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("sport_organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "coach_id",
            sa.Integer(),
            sa.ForeignKey("sport_coaches.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("price", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duration_minutes", sa.Integer(), server_default="60", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
    )

    # 3. Add fields to sport_bookings
    op.add_column("sport_bookings", sa.Column("coach_id", sa.Integer(), nullable=True))
    op.add_column("sport_bookings", sa.Column("service_id", sa.Integer(), nullable=True))
    op.add_column("sport_bookings", sa.Column("start_time", sa.DateTime(timezone=False), nullable=True))
    op.add_column("sport_bookings", sa.Column("end_time", sa.DateTime(timezone=False), nullable=True))
    op.add_column("sport_bookings", sa.Column("price", sa.Integer(), nullable=True))

    op.create_foreign_key(
        "fk_sport_bookings_coach_id_sport_coaches",
        "sport_bookings",
        "sport_coaches",
        ["coach_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_sport_bookings_service_id_sport_services",
        "sport_bookings",
        "sport_services",
        ["service_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_sport_bookings_coach_id", "sport_bookings", ["coach_id"])
    op.create_index("ix_sport_bookings_service_id", "sport_bookings", ["service_id"])


def downgrade() -> None:
    op.drop_index("ix_sport_bookings_service_id", table_name="sport_bookings")
    op.drop_index("ix_sport_bookings_coach_id", table_name="sport_bookings")
    op.drop_constraint("fk_sport_bookings_service_id_sport_services", "sport_bookings", type_="foreignkey")
    op.drop_constraint("fk_sport_bookings_coach_id_sport_coaches", "sport_bookings", type_="foreignkey")
    op.drop_column("sport_bookings", "price")
    op.drop_column("sport_bookings", "end_time")
    op.drop_column("sport_bookings", "start_time")
    op.drop_column("sport_bookings", "service_id")
    op.drop_column("sport_bookings", "coach_id")
    op.drop_table("sport_services")
    op.drop_table("sport_coach_schedules")
