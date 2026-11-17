"""Add gym membership, business data and moderation.

Revision ID: b713c9d2a4e1
Revises: a2f6d18b4c90
"""
from typing import Sequence, Union
import json

import sqlalchemy as sa
from alembic import op


revision: str = "b713c9d2a4e1"
down_revision: Union[str, Sequence[str], None] = "a2f6d18b4c90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sport_organizations", sa.Column("address", sa.String(300), nullable=True))
    op.add_column("sport_organizations", sa.Column("phone", sa.String(24), nullable=True))
    op.add_column("sport_organizations", sa.Column("email", sa.String(254), nullable=True))
    op.add_column("sport_organizations", sa.Column("creator_id", sa.Integer(), nullable=True))
    op.add_column(
        "sport_organizations",
        sa.Column("moderation_status", sa.String(20), server_default="approved", nullable=False),
    )
    op.add_column("sport_organizations", sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_sport_organizations_creator_id_users",
        "sport_organizations",
        "users",
        ["creator_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_sport_organizations_creator_id", "sport_organizations", ["creator_id"])

    op.create_table(
        "sport_gym_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("sport_organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_creator", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_sport_gym_member"),
        sa.CheckConstraint("role IN ('owner', 'admin')", name="ck_sport_gym_member_role"),
    )
    op.create_index("ix_sport_gym_members_organization_id", "sport_gym_members", ["organization_id"])
    op.create_index("ix_sport_gym_members_user_id", "sport_gym_members", ["user_id"])

    op.create_table(
        "sport_venues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("sport_organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("address", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("hours", sa.String(160), server_default="", nullable=False),
        sa.Column("photo_url", sa.String(500), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.create_index("ix_sport_venues_organization_id", "sport_venues", ["organization_id"])

    op.create_table(
        "sport_coaches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("sport_organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("role", sa.String(160), server_default="Тренер", nullable=False),
        sa.Column("tags", sa.String(300), server_default="", nullable=False),
        sa.Column("experience", sa.String(160), server_default="", nullable=False),
        sa.Column("bio", sa.Text(), server_default="", nullable=False),
        sa.Column("photo_url", sa.String(500), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_sport_coach_org_user"),
    )
    op.create_index("ix_sport_coaches_organization_id", "sport_coaches", ["organization_id"])
    op.create_index("ix_sport_coaches_user_id", "sport_coaches", ["user_id"])

    op.create_table(
        "sport_disciplines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("sport_organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("level", sa.String(120), server_default="", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.create_index("ix_sport_disciplines_organization_id", "sport_disciplines", ["organization_id"])

    op.create_table(
        "sport_membership_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("sport_organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("unit", sa.String(80), server_default="", nullable=False),
        sa.Column("items", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("featured", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.UniqueConstraint("organization_id", "code", name="uq_sport_membership_plan_org_code"),
        sa.CheckConstraint("price >= 0", name="ck_sport_membership_plan_price"),
    )
    op.create_index("ix_sport_membership_plans_organization_id", "sport_membership_plans", ["organization_id"])

    op.create_table(
        "sport_gallery_images",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("sport_organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("image_url", sa.String(500), nullable=False),
        sa.Column("alt_text", sa.String(200), server_default="", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.create_index("ix_sport_gallery_images_organization_id", "sport_gallery_images", ["organization_id"])

    op.create_table(
        "sport_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("sport_organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("sport_membership_plans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("member_name", sa.String(160), nullable=False),
        sa.Column("plan_name", sa.String(120), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("method", sa.String(80), server_default="", nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount >= 0", name="ck_sport_payment_amount"),
        sa.CheckConstraint("status IN ('paid', 'pending')", name="ck_sport_payment_status"),
    )
    op.create_index("ix_sport_payments_organization_id", "sport_payments", ["organization_id"])
    op.create_index("ix_sport_payments_client_id", "sport_payments", ["client_id"])

    op.add_column("sport_trainings", sa.Column("coach_id", sa.Integer(), nullable=True))
    op.add_column("sport_trainings", sa.Column("venue_id", sa.Integer(), nullable=True))
    op.add_column("sport_trainings", sa.Column("discipline_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_sport_trainings_coach_id", "sport_trainings", "sport_coaches", ["coach_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_sport_trainings_venue_id", "sport_trainings", "sport_venues", ["venue_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_sport_trainings_discipline_id", "sport_trainings", "sport_disciplines", ["discipline_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_sport_trainings_coach_id", "sport_trainings", ["coach_id"])
    op.create_index("ix_sport_trainings_venue_id", "sport_trainings", ["venue_id"])
    op.create_index("ix_sport_trainings_discipline_id", "sport_trainings", ["discipline_id"])

    bind = op.get_bind()
    organization_id = bind.execute(
        sa.text("SELECT id FROM sport_organizations WHERE slug = 'sparta'")
    ).scalar_one_or_none()
    if organization_id is not None:
        venues = [
            ("Основной зал", "Иркутский тракт, 68", "Зал для тренировок на Иркутском тракте.", "По расписанию групп", "/photos/gyms/irk-01.png", 0),
            ("ЦНПК", "пр. Фрунзе, 115/3", "Зал ЦНПК.", "По расписанию групп", None, 1),
            ("Зал СибГМУ", "ул. Учебная, 40 · корпус СибГМУ", "Зал СибГМУ.", "По расписанию групп", None, 2),
        ]
        venue_ids = {}
        for name, address, description, hours, photo_url, order in venues:
            venue_ids[address] = bind.execute(
                sa.text(
                    "INSERT INTO sport_venues "
                    "(organization_id, name, address, description, hours, photo_url, sort_order, is_active) "
                    "VALUES (:org, :name, :address, :description, :hours, :photo_url, :order, true) "
                    "RETURNING id"
                ),
                {"org": organization_id, "name": name, "address": address, "description": description, "hours": hours, "photo_url": photo_url, "order": order},
            ).scalar_one()

        coaches = [
            ("Давыдов Дмитрий Михайлович", "Руководитель клуба · тренер", "Иркутский тракт · СибГМУ", "6 дан CJJIF", "Руководитель клуба «Спарта Плюс». Проводит тренировки в основном зале на Иркутском тракте и в корпусе СибГМУ.", "/photos/coaches/dmitry.png", 0),
            ("Давыдов Аким Дмитриевич", "Тренер", "ЦНПК · пр. Фрунзе, 115/3", "Пн · Ср · Пт", "Тренер клуба «Спарта Плюс». Проводит занятия на проспекте Фрунзе, 115/3.", "/photos/coaches/akim.png", 1),
            ("Дмитриев Богдан Дмитриевич", "Тренер", "Основной зал · Иркутский тракт, 68", "Вт · Чт · Сб", "Тренер клуба «Спарта Плюс». Проводит занятия в основном зале на Иркутском тракте, 68.", "/photos/coaches/bogdan.png", 2),
        ]
        coach_ids = {}
        for name, role, tags, experience, bio, photo_url, order in coaches:
            coach_ids[name] = bind.execute(
                sa.text(
                    "INSERT INTO sport_coaches "
                    "(organization_id, name, role, tags, experience, bio, photo_url, sort_order, is_active) "
                    "VALUES (:org, :name, :role, :tags, :experience, :bio, :photo_url, :order, true) "
                    "RETURNING id"
                ),
                {"org": organization_id, "name": name, "role": role, "tags": tags, "experience": experience, "bio": bio, "photo_url": photo_url, "order": order},
            ).scalar_one()

        disciplines = [
            ("БЖЖ", "Борьба, контроль и техника в партере. Группу и возраст уточнит тренер.", "Для детей и взрослых"),
            ("Грэпплинг", "Борьба без кимоно: захваты, броски и работа в партере.", "Группу уточнит тренер"),
            ("ММА", "Ударная техника и борьба в одной программе.", "Группу уточнит тренер"),
            ("Самооборона", "Прикладные навыки для уверенного поведения в сложных ситуациях.", "По заявке"),
            ("Самбо", "Техника бросков, захватов и борьбы в партере.", "Группу уточнит тренер"),
        ]
        for order, (name, description, level) in enumerate(disciplines):
            bind.execute(
                sa.text(
                    "INSERT INTO sport_disciplines "
                    "(organization_id, name, description, level, sort_order, is_active) "
                    "VALUES (:org, :name, :description, :level, :order, true)"
                ),
                {"org": organization_id, "name": name, "description": description, "level": level, "order": order},
            )

        plans = [
            ("trial", "Пробное", 0, "первое занятие", ["Ознакомительная тренировка", "Знакомство с тренером и залом"], 0),
            ("base", "Абонемент", 5000, "в месяц", ["Безлимит на календарный месяц", "Можно посещать занятия по расписанию"], 1),
        ]
        for code, name, price, unit, items, order in plans:
            bind.execute(
                sa.text(
                    "INSERT INTO sport_membership_plans "
                    "(organization_id, code, name, price, unit, items, sort_order, is_active) "
                    "VALUES (:org, :code, :name, :price, :unit, CAST(:items AS json), :order, true)"
                ),
                {"org": organization_id, "code": code, "name": name, "price": price, "unit": unit, "items": json.dumps(items), "order": order},
            )

        gallery_images = [
            ("/photos/club/hero.jpg", "Команда клуба"),
            ("/photos/club/why-kids.png", "Детские тренировки"),
            ("/photos/club/why-beginner.png", "Тренировка для начинающих"),
            ("/photos/disciplines/bjj.png", "Бразильское джиу-джитсу"),
            ("/photos/disciplines/grappling.png", "Грэпплинг"),
            ("/photos/disciplines/self-defense-01.png", "Самооборона"),
        ]
        for order, (image_url, alt_text) in enumerate(gallery_images):
            bind.execute(
                sa.text(
                    "INSERT INTO sport_gallery_images "
                    "(organization_id, image_url, alt_text, sort_order, is_active) "
                    "VALUES (:org, :url, :alt, :order, true)"
                ),
                {
                    "org": organization_id,
                    "url": image_url,
                    "alt": alt_text,
                    "order": order,
                },
            )

        for training in bind.execute(
            sa.text("SELECT id, coach, gym FROM sport_trainings WHERE organization_id = :org"),
            {"org": organization_id},
        ).mappings():
            bind.execute(
                sa.text(
                    "UPDATE sport_trainings SET coach_id = :coach, venue_id = :venue "
                    "WHERE id = :id"
                ),
                {
                    "id": training["id"],
                    "coach": coach_ids.get(training["coach"]),
                    "venue": venue_ids.get(training["gym"]),
                },
            )


def downgrade() -> None:
    op.drop_index("ix_sport_trainings_discipline_id", table_name="sport_trainings")
    op.drop_index("ix_sport_trainings_venue_id", table_name="sport_trainings")
    op.drop_index("ix_sport_trainings_coach_id", table_name="sport_trainings")
    op.drop_constraint("fk_sport_trainings_discipline_id", "sport_trainings", type_="foreignkey")
    op.drop_constraint("fk_sport_trainings_venue_id", "sport_trainings", type_="foreignkey")
    op.drop_constraint("fk_sport_trainings_coach_id", "sport_trainings", type_="foreignkey")
    op.drop_column("sport_trainings", "discipline_id")
    op.drop_column("sport_trainings", "venue_id")
    op.drop_column("sport_trainings", "coach_id")

    op.drop_index("ix_sport_payments_client_id", table_name="sport_payments")
    op.drop_index("ix_sport_payments_organization_id", table_name="sport_payments")
    op.drop_table("sport_payments")
    op.drop_index("ix_sport_gallery_images_organization_id", table_name="sport_gallery_images")
    op.drop_table("sport_gallery_images")
    op.drop_index("ix_sport_membership_plans_organization_id", table_name="sport_membership_plans")
    op.drop_table("sport_membership_plans")
    op.drop_index("ix_sport_disciplines_organization_id", table_name="sport_disciplines")
    op.drop_table("sport_disciplines")
    op.drop_index("ix_sport_coaches_user_id", table_name="sport_coaches")
    op.drop_index("ix_sport_coaches_organization_id", table_name="sport_coaches")
    op.drop_table("sport_coaches")
    op.drop_index("ix_sport_venues_organization_id", table_name="sport_venues")
    op.drop_table("sport_venues")
    op.drop_index("ix_sport_gym_members_user_id", table_name="sport_gym_members")
    op.drop_index("ix_sport_gym_members_organization_id", table_name="sport_gym_members")
    op.drop_table("sport_gym_members")

    op.drop_index("ix_sport_organizations_creator_id", table_name="sport_organizations")
    op.drop_constraint("fk_sport_organizations_creator_id_users", "sport_organizations", type_="foreignkey")
    op.drop_column("sport_organizations", "rejection_reason")
    op.drop_column("sport_organizations", "moderation_status")
    op.drop_column("sport_organizations", "creator_id")
    op.drop_column("sport_organizations", "email")
    op.drop_column("sport_organizations", "phone")
    op.drop_column("sport_organizations", "address")
