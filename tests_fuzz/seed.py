"""Данные для фаззинга: известные id, чтобы пути вида /masters/{id} попадали в
живой код, а не только в 404. Телефоны с заведомо уникальным префиксом
(+7999 FUZZ…) — чистить «похожее» запрещено, поэтому тут никто ничего не удаляет:
таблицы обнуляет штатная фикстура _clean_state.
"""
from datetime import datetime, timedelta, timezone

from app.core.security import create_access_token, get_password_hash
from app.models.models import (
    Booking, BookingStatus, Master, Salon, SalonMember, SalonModerationStatus,
    SalonRole, SalonSubscriptionStatus, Service, User, UserRole,
)


async def seed(db_session) -> dict:
    """Владелец салона (id=1), мастер (id=2), клиент (id=3), салон/мастер/
    услуга/запись с id=1. Возвращает токены по именам ролей."""
    pw = get_password_hash("Fuzzpass1")
    async with db_session() as db:
        owner = User(phone="+79990000001", full_name="Владелец Фаз",
                     hashed_password=pw, role=UserRole.BUSINESS)
        muser = User(phone="+79990000002", full_name="Мастер Фаз",
                     hashed_password=pw, role=UserRole.MASTER)
        client = User(phone="+79990000003", full_name="Клиент Фаз",
                      hashed_password=pw, role=UserRole.CLIENT)
        db.add_all([owner, muser, client])
        await db.commit()
        for u in (owner, muser, client):
            await db.refresh(u)

        salon = Salon(name="Салон Фаз", description="", address="Томск, ул. 1",
                      latitude=56.5, longitude=84.9, phone="+79990001111",
                      city="Томск", is_active=True, creator_id=owner.id,
                      moderation_status=SalonModerationStatus.APPROVED,
                      subscription_status=SalonSubscriptionStatus.ACTIVE,
                      access_until=datetime.now(timezone.utc) + timedelta(days=30))
        db.add(salon)
        await db.commit()
        await db.refresh(salon)
        db.add(SalonMember(salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER,
                           is_creator=True, permissions={"manage_salon": True},
                           is_active=True))
        master = Master(user_id=muser.id, salon_id=salon.id, specialization="Маникюр",
                        is_active=True)
        db.add(master)
        await db.commit()
        await db.refresh(master)
        service = Service(master_id=master.id, name="Маникюр", price=1000,
                          duration_minutes=60, is_active=True)
        db.add(service)
        await db.commit()
        await db.refresh(service)
        start = (datetime.now() + timedelta(days=1)).replace(hour=12, minute=0,
                                                              second=0, microsecond=0)
        db.add(Booking(client_id=client.id, master_id=master.id, service_id=service.id,
                       start_time=start, end_time=start + timedelta(minutes=60),
                       status=BookingStatus.PENDING))
        await db.commit()
        return {
            "owner": create_access_token(owner.id),
            "client": create_access_token(client.id),
        }
