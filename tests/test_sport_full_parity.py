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
async def test_sport_full_parity_features(client, db_session):
    async with db_session() as session:
        # 1. Owner & Org
        owner = User(
            email="sport_owner@test.com",
            phone="+79991110011",
            full_name="Спорт Владелец",
            hashed_password="hash",
            is_active=True,
        )
        session.add(owner)
        await session.flush()

        org = SportOrganization(
            slug="olympus-pro",
            name="Olympus Pro",
            city="Екатеринбург",
            address="ул. Мира, 1",
            is_published=True,
            moderation_status="approved",
        )
        session.add(org)
        await session.flush()

        session.add(SportGymMember(
            organization_id=org.id,
            user_id=owner.id,
            role="owner",
            is_creator=True,
            is_active=True,
        ))

        # Coach
        coach = SportCoach(
            organization_id=org.id,
            name="Дмитрий Волков",
            role="Тренер по плаванию",
            experience="8 лет",
            is_active=True,
        )
        session.add(coach)
        await session.commit()
        coach_id = coach.id

    token = create_access_token(subject=owner.id)
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Add Manager (Управляющий)
    resp_mgr = await client.post(
        f"/api/v1/sport/organizations/{org.slug}/staff",
        headers=headers,
        data={
            "phone": "+79992220022",
            "name": "Анна Управляющая",
            "role": "manager",
        },
    )
    assert resp_mgr.status_code == 200, resp_mgr.text
    mgr_data = resp_mgr.json()
    assert mgr_data["role"] == "manager"

    # 3. Add Service & Coach Schedule
    resp_svc = await client.post(
        f"/api/v1/sport/organizations/{org.slug}/manage/services",
        headers=headers,
        json={
            "coach_id": coach_id,
            "name": "Индивидуальная тренировка по плаванию",
            "price": 2500,
            "duration_minutes": 60,
        },
    )
    assert resp_svc.status_code == 200
    service_id = resp_svc.json()["id"]

    # Mon-Sun 09:00 - 15:00
    schedules = [
        {
            "day_of_week": day,
            "start_time": "09:00",
            "end_time": "15:00",
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
    assert resp_sched.status_code == 200

    # 4. Closures (Отпуск тренера на дату)
    vacation_day = date.today() + timedelta(days=2)
    resp_close = await client.post(
        f"/api/v1/sport/organizations/{org.slug}/closures",
        headers=headers,
        json={
            "coach_id": coach_id,
            "date": vacation_day.isoformat(),
            "reason": "Отпуск тренера",
        },
    )
    assert resp_close.status_code == 200
    closure_id = resp_close.json()["id"]

    # Available slots on vacation day should be empty
    resp_slots_vac = await client.get(
        f"/api/v1/sport/coaches/{coach_id}/available-slots?date={vacation_day.isoformat()}"
    )
    assert resp_slots_vac.status_code == 200
    assert resp_slots_vac.json()["slots"] == []

    # 5. Book on normal day (tomorrow)
    tomorrow = date.today() + timedelta(days=1)
    book_time = datetime.combine(tomorrow, time(9, 0))
    resp_book = await client.post(
        f"/api/v1/sport/organizations/{org.slug}/book-coach",
        json={
            "coach_id": coach_id,
            "service_id": service_id,
            "start_time": book_time.isoformat(),
            "name": "Клиент Про",
            "phone": "+79993334455",
            "consent_version": LEGAL_VERSION,
            "pd_consent": True,
        },
    )
    assert resp_book.status_code == 201
    booking_id = resp_book.json()["booking_id"]

    # 6. Reschedule booking to 10:15
    new_time = datetime.combine(tomorrow, time(10, 15))
    resp_resched = await client.post(
        f"/api/v1/sport/organizations/{org.slug}/bookings/{booking_id}/reschedule",
        headers=headers,
        json={"new_start_time": new_time.isoformat()},
    )
    assert resp_resched.status_code == 200
    assert resp_resched.json()["ok"] is True

    # 7. Reviews (Отзывы и ответы)
    resp_rev = await client.post(
        f"/api/v1/sport/organizations/{org.slug}/reviews",
        headers=headers,
        json={
            "coach_id": coach_id,
            "booking_id": booking_id,
            "rating": 5,
            "comment": "Отличный тренер, поставил технику кроля за одно занятие!",
        },
    )
    assert resp_rev.status_code == 200
    review_id = resp_rev.json()["id"]

    # Reply to review
    resp_reply = await client.post(
        f"/api/v1/sport/organizations/{org.slug}/reviews/{review_id}/reply",
        headers=headers,
        json={"admin_response": "Спасибо за отзыв! Ждём вас снова."},
    )
    assert resp_reply.status_code == 200
    assert resp_reply.json()["admin_response"] == "Спасибо за отзыв! Ждём вас снова."

    # 8. Coach Payroll (Ставки и расчет вознаграждения)
    resp_payroll = await client.post(
        f"/api/v1/sport/organizations/{org.slug}/coaches/{coach_id}/payroll",
        headers=headers,
        json={
            "commission_percent": 60,
            "base_rate_per_session": 500,
            "bonus": 1000,
            "notes": "Старший тренер",
        },
    )
    assert resp_payroll.status_code == 200
    payroll_data = resp_payroll.json()
    assert payroll_data["commission_percent"] == 60
    assert payroll_data["base_rate_per_session"] == 500

    # Summary
    resp_summary = await client.get(
        f"/api/v1/sport/organizations/{org.slug}/coaches/{coach_id}/payroll/summary",
        headers=headers,
    )
    assert resp_summary.status_code == 200
    summary = resp_summary.json()
    assert "total_payout" in summary
    assert summary["commission_percent"] == 60

    # 9. Cancel booking
    resp_cancel = await client.post(
        f"/api/v1/sport/organizations/{org.slug}/bookings/{booking_id}/cancel",
        headers=headers,
    )
    assert resp_cancel.status_code == 200
    assert resp_cancel.json()["status"] == "cancelled"
