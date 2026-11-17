"""Add sports organizations, schedule and guest bookings.

Revision ID: a2f6d18b4c90
Revises: c2f8a1d44e07
"""
from typing import Sequence, Union
from datetime import time

import sqlalchemy as sa
from alembic import op


revision: str = "a2f6d18b4c90"
down_revision: Union[str, Sequence[str], None] = "c2f8a1d44e07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sport_organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("logo_url", sa.String(length=500), nullable=True),
        sa.Column("is_published", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sport_organizations_slug", "sport_organizations", ["slug"], unique=True)

    op.create_table(
        "sport_trainings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("sport_organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("weekdays", sa.JSON(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("coach", sa.String(length=160), nullable=False),
        sa.Column("gym", sa.String(length=200), nullable=False),
        sa.Column("discipline", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.UniqueConstraint("organization_id", "code", name="uq_sport_training_org_code"),
    )
    op.create_index("ix_sport_trainings_organization_id", "sport_trainings", ["organization_id"])

    op.create_table(
        "sport_training_exceptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "training_id",
            sa.Integer(),
            sa.ForeignKey("sport_trainings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("class_date", sa.Date(), nullable=False),
        sa.Column("is_cancelled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.UniqueConstraint("training_id", "class_date", name="uq_sport_training_exception_date"),
    )
    op.create_index("ix_sport_training_exceptions_training_id", "sport_training_exceptions", ["training_id"])

    op.create_table(
        "sport_bookings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("sport_organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "training_id",
            sa.Integer(),
            sa.ForeignKey("sport_trainings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("contact_name", sa.String(length=100), nullable=False),
        sa.Column("participant", sa.String(length=12), nullable=False),
        sa.Column("child_name", sa.String(length=100), nullable=True),
        sa.Column("child_age", sa.Integer(), nullable=True),
        sa.Column("contact_email", sa.String(length=254), nullable=True),
        sa.Column("experience", sa.String(length=80), nullable=True),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("requested_date", sa.Date(), nullable=True),
        sa.Column("requested_gym", sa.String(length=200), nullable=False),
        sa.Column("requested_discipline", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("participant IN ('self', 'child')", name="ck_sport_booking_participant"),
    )
    op.create_index("ix_sport_bookings_organization_id", "sport_bookings", ["organization_id"])
    op.create_index("ix_sport_bookings_training_id", "sport_bookings", ["training_id"])
    op.create_index("ix_sport_bookings_client_id", "sport_bookings", ["client_id"])

    organizations = sa.table(
        "sport_organizations",
        sa.column("id", sa.Integer()),
        sa.column("slug", sa.String()),
        sa.column("name", sa.String()),
        sa.column("city", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("logo_url", sa.String()),
        sa.column("is_published", sa.Boolean()),
        sa.column("sort_order", sa.Integer()),
    )
    organization_id = op.get_bind().execute(
        sa.insert(organizations)
        .values(
            slug="sparta",
            name="Спарта Плюс",
            city="Томск",
            description="Клуб боевого дзю-дзютцу: БЖЖ, грэпплинг, ММА, самбо и самооборона для детей и взрослых.",
            logo_url="/static/sport/sparta/sparta-logo.png",
            is_published=True,
            sort_order=10,
        )
        .returning(organizations.c.id)
    ).scalar_one()

    trainings = sa.table(
        "sport_trainings",
        sa.column("id", sa.Integer()),
        sa.column("organization_id", sa.Integer()),
        sa.column("code", sa.String()),
        sa.column("weekdays", sa.JSON()),
        sa.column("start_time", sa.Time()),
        sa.column("end_time", sa.Time()),
        sa.column("coach", sa.String()),
        sa.column("gym", sa.String()),
        sa.column("discipline", sa.String()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        trainings,
        [
            {"organization_id": organization_id, "code": "dm-irk", "weekdays": [1, 3, 5], "start_time": time(20, 0), "end_time": time(21, 30), "coach": "Давыдов Дмитрий Михайлович", "gym": "Иркутский тракт, 68", "discipline": "Направление уточняется", "is_active": True},
            {"organization_id": organization_id, "code": "dm-ssmu", "weekdays": [2, 4], "start_time": time(19, 0), "end_time": time(20, 30), "coach": "Давыдов Дмитрий Михайлович", "gym": "ул. Учебная, 40 · корпус СибГМУ", "discipline": "Направление уточняется", "is_active": True},
            {"organization_id": organization_id, "code": "dm-sat", "weekdays": [6], "start_time": time(18, 0), "end_time": time(20, 0), "coach": "Давыдов Дмитрий Михайлович", "gym": "Иркутский тракт, 68", "discipline": "Направление уточняется", "is_active": True},
            {"organization_id": organization_id, "code": "ak-fr", "weekdays": [1, 3, 5], "start_time": time(19, 45), "end_time": time(21, 15), "coach": "Давыдов Аким Дмитриевич", "gym": "пр. Фрунзе, 115/3", "discipline": "Направление уточняется", "is_active": True},
            {"organization_id": organization_id, "code": "bd-irk", "weekdays": [2, 4, 6], "start_time": time(20, 0), "end_time": time(21, 30), "coach": "Дмитриев Богдан Дмитриевич", "gym": "Иркутский тракт, 68", "discipline": "Направление уточняется", "is_active": True},
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_sport_bookings_client_id", table_name="sport_bookings")
    op.drop_index("ix_sport_bookings_training_id", table_name="sport_bookings")
    op.drop_index("ix_sport_bookings_organization_id", table_name="sport_bookings")
    op.drop_table("sport_bookings")
    op.drop_index("ix_sport_training_exceptions_training_id", table_name="sport_training_exceptions")
    op.drop_table("sport_training_exceptions")
    op.drop_index("ix_sport_trainings_organization_id", table_name="sport_trainings")
    op.drop_table("sport_trainings")
    op.drop_index("ix_sport_organizations_slug", table_name="sport_organizations")
    op.drop_table("sport_organizations")
