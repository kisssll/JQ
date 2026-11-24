from datetime import datetime, date, time, timedelta
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.models import User
from app.models.sport import (
    SportCoach,
    SportCoachSchedule,
    SportGymMember,
    SportOrganization,
    SportService,
)
from app.web.pages.legal import LEGAL_VERSION


@pytest.mark.asyncio
async def test_sport_coach_individual_booking_flow(client, db_session):
    async with db_session() as session:
        # 1. Create owner and organization
        owner = User(
            email="owner_coach@test.com",
            phone="+79997776655",
            full_name="Club Owner",
            hashed_password="hash",
            is_active=True,
        )
        session.add(owner)
        await session.flush()

        org = SportOrganization(
            slug="strike-club",
            name="Strike Club",
            city="Москва",
            address="ул. Спортивная, 1",
            is_published=True,
            moderation_status="approved",
        )
        session.add(org)
        await session.flush()

        member = SportGymMember(
            organization_id=org.id,
            user_id=owner.id,
            role="owner",
            is_active=True,
        )
        session.add(member)

        # 2. Add coach
        coach = SportCoach(
            organization_id=org.id,
            name="Алексей Смирнов",
            role="Главный тренер по боксу",
            experience="10 лет",
            is_active=True,
        )
        session.add(coach)
        await session.commit()
        coach_id = coach.id

    token = create_access_token(subject=owner.id)
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Add coach service (personal training)
    resp_svc = await client.post(
        f"/api/v1/sport/organizations/{org.slug}/manage/services",
        headers=headers,
        json={
            "coach_id": coach_id,
            "name": "Персональная тренировка по боксу",
            "description": "Постановка техники и спарринг",
            "price": 3000,
            "duration_minutes": 60,
        },
    )
    assert resp_svc.status_code == 200, resp_svc.text
    svc_data = resp_svc.json()
    service_id = svc_data["id"]

    # 4. Configure coach static schedule windows
    # Schedule for Monday through Sunday (all days) from 10:00 to 18:00
    schedules = [
        {
            "day_of_week": day,
            "start_time": "10:00",
            "end_time": "18:00",
            "slot_duration_minutes": 60,
            "break_minutes": 15,
        }
        for day in range(7)
    ]
    resp_sched = await client.post(
        f"/api/v1/sport/organizations/{org.slug}/coaches/{coach_id}/schedule",
        headers=headers,
        json={"schedules": schedules},
    )
    assert resp_sched.status_code == 200, resp_sched.text

    # 5. Get coach services
    resp_get_svc = await client.get(f"/api/v1/sport/coaches/{coach_id}/services")
    assert resp_get_svc.status_code == 200
    services = resp_get_svc.json()
    assert len(services) == 1
    assert services[0]["name"] == "Персональная тренировка по боксу"

    # 6. Get available slots for tomorrow
    tomorrow = date.today() + timedelta(days=1)
    tomorrow_str = tomorrow.strftime("%Y-%m-%d")
    resp_slots = await client.get(f"/api/v1/sport/coaches/{coach_id}/available-slots?date={tomorrow_str}")
    assert resp_slots.status_code == 200, resp_slots.text
    slots_data = resp_slots.json()
    assert "10:00" in slots_data["slots"]
    # Next slot is 10:00 + 60m + 15m break = 11:15
    assert "11:15" in slots_data["slots"]

    # 7. Book 10:00 slot
    book_time = datetime.combine(tomorrow, time(10, 0))
    resp_book = await client.post(
        f"/api/v1/sport/organizations/{org.slug}/book-coach",
        json={
            "coach_id": coach_id,
            "service_id": service_id,
            "start_time": book_time.isoformat(),
            "name": "Иван Клиент",
            "phone": "+79991234567",
            "consent_version": LEGAL_VERSION,
            "pd_consent": True,
        },
    )
    assert resp_book.status_code == 201, resp_book.text
    booking_res = resp_book.json()
    assert booking_res["ok"] is True
    assert booking_res["coach"] == "Алексей Смирнов"
    assert booking_res["service"] == "Персональная тренировка по боксу"
    assert booking_res["price"] == 3000

    # 8. Check that 10:00 is now occupied and disappears from available slots
    resp_slots_after = await client.get(f"/api/v1/sport/coaches/{coach_id}/available-slots?date={tomorrow_str}")
    assert resp_slots_after.status_code == 200
    slots_after = resp_slots_after.json()["slots"]
    assert "10:00" not in slots_after
    assert "11:15" in slots_after

    # 9. Duplicate booking attempt for 10:00 returns 409 Conflict
    resp_dup = await client.post(
        f"/api/v1/sport/organizations/{org.slug}/book-coach",
        json={
            "coach_id": coach_id,
            "service_id": service_id,
            "start_time": book_time.isoformat(),
            "name": "Второй Клиент",
            "phone": "+79998889900",
            "consent_version": LEGAL_VERSION,
            "pd_consent": True,
        },
    )
    assert resp_dup.status_code == 409
    assert "уже занято" in resp_dup.text or "не работает" in resp_dup.text
