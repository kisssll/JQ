from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.models import Base


class SportOrganization(Base):
    __tablename__ = "sport_organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    logo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    cover_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    site_documents: Mapped[Optional[list[dict]]] = mapped_column(JSON, nullable=True)
    training_agreements: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    vk_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    telegram_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(254), nullable=True)
    creator_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    moderation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="approved", server_default="approved"
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    subscription_tier: Mapped[Optional[str]] = mapped_column(String(30), nullable=True, default="gym", server_default="gym")
    subscription_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="trialing", server_default="trialing"
    )
    subscription_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    custom_subscription_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    custom_subscription_notes: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


SPORT_PERMISSION_KEYS = (
    "manage_gym",         # настройки клуба, залов, фото, профиля
    "manage_owners",      # передача владения, назначение совладельцев
    "manage_managers",    # назначение управляющих
    "manage_admins",      # назначение администраторов
    "manage_coaches",     # найм тренеров, услуги, графики
    "manage_schedule",    # расписание групповых и персональных тренировок
    "manage_bookings",    # подтверждение, отмена, отметка посещения / неявки
    "manage_reviews",     # ответы на отзывы
    "view_finances",      # отчёты о выручке, аналитика
    "manage_payroll",     # ставки тренеров, расчёт зарплат
)

SPORT_OWNER_PERMISSIONS: dict[str, bool] = {k: True for k in SPORT_PERMISSION_KEYS}
SPORT_MANAGER_PERMISSIONS: dict[str, bool] = {
    **SPORT_OWNER_PERMISSIONS,
    "manage_owners": False,
}
SPORT_ADMIN_PERMISSIONS: dict[str, bool] = {
    **SPORT_OWNER_PERMISSIONS,
    "manage_owners": False,
    "manage_managers": False,
    "view_finances": False,
    "manage_payroll": False,
}


class SportGymMember(Base):
    __tablename__ = "sport_gym_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_sport_gym_member"),
        CheckConstraint("role IN ('owner', 'manager', 'admin')", name="ck_sport_gym_member_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("sport_organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    photo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    permissions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_creator: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SportScheduleClosure(Base):
    """Закрытые даты (отпуск / больничный тренера либо ремонт / закрытие зала / всего клуба)."""
    __tablename__ = "sport_schedule_closures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("sport_organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    coach_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sport_coaches.id", ondelete="CASCADE"), nullable=True, index=True
    )
    venue_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sport_venues.id", ondelete="CASCADE"), nullable=True, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SportReview(Base):
    """Отзывы клиентов о клубе и тренерах."""
    __tablename__ = "sport_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("sport_organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    coach_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sport_coaches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    client_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    booking_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sport_bookings.id", ondelete="SET NULL"), nullable=True, index=True
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-5
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    admin_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SportCoachPayroll(Base):
    """Условия оплаты и расчет вознаграждения тренера."""
    __tablename__ = "sport_coach_payrolls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("sport_organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    coach_id: Mapped[int] = mapped_column(
        ForeignKey("sport_coaches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    commission_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=50, server_default="50")
    base_rate_per_session: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    bonus: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    notes: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SportVenue(Base):
    __tablename__ = "sport_venues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("sport_organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    address: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    hours: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    photo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class SportCoach(Base):
    __tablename__ = "sport_coaches"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_sport_coach_org_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("sport_organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    role: Mapped[str] = mapped_column(String(160), nullable=False, default="Тренер")
    tags: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    experience: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    bio: Mapped[str] = mapped_column(Text, nullable=False, default="")
    photo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SportDiscipline(Base):
    __tablename__ = "sport_disciplines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("sport_organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    level: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    photo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class SportMembershipPlan(Base):
    __tablename__ = "sport_membership_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("sport_organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    items: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_sport_membership_plan_org_code"),
        CheckConstraint("price >= 0", name="ck_sport_membership_plan_price"),
    )


class SportGalleryImage(Base):
    __tablename__ = "sport_gallery_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("sport_organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    alt_text: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class SportPayment(Base):
    __tablename__ = "sport_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("sport_organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    plan_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sport_membership_plans.id", ondelete="SET NULL"), nullable=True
    )
    member_name: Mapped[str] = mapped_column(String(160), nullable=False)
    plan_name: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    month: Mapped[str] = mapped_column(String(7), nullable=False)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    method: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    created_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_sport_payment_amount"),
        CheckConstraint("status IN ('paid', 'pending')", name="ck_sport_payment_status"),
    )


class SportTraining(Base):
    __tablename__ = "sport_trainings"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_sport_training_org_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("sport_organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    weekdays: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    coach: Mapped[str] = mapped_column(String(160), nullable=False)
    gym: Mapped[str] = mapped_column(String(200), nullable=False)
    discipline: Mapped[str] = mapped_column(String(120), nullable=False)
    coach_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sport_coaches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    venue_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sport_venues.id", ondelete="SET NULL"), nullable=True, index=True
    )
    discipline_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sport_disciplines.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class SportTrainingException(Base):
    __tablename__ = "sport_training_exceptions"
    __table_args__ = (
        UniqueConstraint("training_id", "class_date", name="uq_sport_training_exception_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    training_id: Mapped[int] = mapped_column(
        ForeignKey("sport_trainings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    class_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_cancelled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class SportCoachSchedule(Base):
    """Статичные окна/график тренера по дням недели (0=понедельник ... 6=воскресенье)."""
    __tablename__ = "sport_coach_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    coach_id: Mapped[int] = mapped_column(
        ForeignKey("sport_coaches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Mon, 6=Sun
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    slot_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60, server_default="60")
    break_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15, server_default="15")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class SportService(Base):
    """Персональные услуги тренеров / клуба (индивидуальная тренировка, консультация и т.д.)."""
    __tablename__ = "sport_services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("sport_organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    coach_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sport_coaches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    price: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60, server_default="60")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class SportBooking(Base):
    __tablename__ = "sport_bookings"
    training_agreement: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    __table_args__ = (
        CheckConstraint(
            "participant IN ('self', 'child')",
            name="ck_sport_booking_participant",
        ),
        Index("ix_sport_bookings_attendance_date", "organization_id", "requested_date",
              postgresql_where=text("status = 'came'")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("sport_organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    training_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sport_trainings.id", ondelete="SET NULL"), nullable=True, index=True
    )
    coach_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sport_coaches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    service_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sport_services.id", ondelete="SET NULL"), nullable=True, index=True
    )
    client_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    contact_name: Mapped[str] = mapped_column(String(100), nullable=False)
    participant: Mapped[str] = mapped_column(String(12), nullable=False)
    child_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    child_age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(String(254), nullable=True)
    experience: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    requested_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    start_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    requested_gym: Mapped[str] = mapped_column(String(200), nullable=False)
    requested_discipline: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
