from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SportGymMember(Base):
    __tablename__ = "sport_gym_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_sport_gym_member"),
        CheckConstraint("role IN ('owner', 'admin')", name="ck_sport_gym_member_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("sport_organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    is_creator: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
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


class SportBooking(Base):
    __tablename__ = "sport_bookings"
    __table_args__ = (
        CheckConstraint(
            "participant IN ('self', 'child')",
            name="ck_sport_booking_participant",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("sport_organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    training_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sport_trainings.id", ondelete="SET NULL"), nullable=True, index=True
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
    requested_gym: Mapped[str] = mapped_column(String(200), nullable=False)
    requested_discipline: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
