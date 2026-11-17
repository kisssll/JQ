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
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
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
