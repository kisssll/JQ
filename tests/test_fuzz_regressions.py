"""Находки фаззинга (tests_fuzz/): мусорный ввод давал 500 вместо 4xx.

Каждый случай закрыт обычным тестом здесь — фаззер лежит отдельно и гейт
выката не держит, а эти ошибки возвращаться не должны.
"""
from datetime import datetime, timedelta, timezone

from app.core.security import create_access_token, get_password_hash
from app.models.models import (
    Salon, SalonMember, SalonModerationStatus, SalonRole, SalonSubscriptionStatus,
    User, UserRole,
)


async def _owner_with_salon(db_session):
    async with db_session() as db:
        owner = User(phone="+79995550001", full_name="Вл", role=UserRole.BUSINESS,
                     hashed_password=get_password_hash("Bizpass1"))
        db.add(owner)
        await db.commit()
        await db.refresh(owner)
        salon = Salon(name="Салон", description="", address="Томск", latitude=56.5,
                      longitude=84.9, phone="+79990001111", city="Томск", is_active=True,
                      creator_id=owner.id, moderation_status=SalonModerationStatus.APPROVED,
                      subscription_status=SalonSubscriptionStatus.ACTIVE,
                      access_until=datetime.now(timezone.utc) + timedelta(days=30))
        db.add(salon)
        await db.commit()
        await db.refresh(salon)
        db.add(SalonMember(salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER,
                           is_creator=True, permissions={"manage_salon": True}, is_active=True))
        await db.commit()
        return {"Authorization": f"Bearer {create_access_token(owner.id)}"}, salon.id


async def test_id_outside_int32_is_422_not_500(client, db_session):
    h, sid = await _owner_with_salon(db_session)
    r = await client.get(f"/api/v1/loyalty/salon/{sid}/settings", headers=h)
    assert r.status_code != 500
    r = await client.get("/api/v1/loyalty/salon/33886555348/settings", headers=h)
    assert r.status_code == 422, r.text
    assert r.json()["detail"][0]["msg"]  # та же форма, что у штатного 422 FastAPI


async def test_nul_byte_in_text_is_422_not_500(client, db_session):
    h, _ = await _owner_with_salon(db_session)
    r = await client.post("/api/v1/business/my-salon/promotions", headers=h,
                          json={"title": "акция\u0000", "tag": "", "description": None})
    assert r.status_code == 422, r.text


async def test_unknown_client_is_4xx_not_500(client, db_session):
    h, sid = await _owner_with_salon(db_session)
    r = await client.post("/api/v1/business/my-salon/clients/16432555/notes",
                          headers=h, json={"text": "заметка"})
    assert r.status_code == 404, r.text
    # loyalty пишет по внешнему ключу без собственной проверки — ловит общий обработчик
    r = await client.post(f"/api/v1/loyalty/salon/{sid}/client/16432555/status",
                          headers=h, json={"is_regular": False})
    assert r.status_code in (404, 422), r.text


async def test_real_db_failure_still_500():
    """Общий обработчик не должен глотать настоящие поломки БД."""
    from sqlalchemy.exc import OperationalError
    from app.main import _db_input_problem

    assert _db_input_problem(OperationalError("select 1", {}, Exception("connection lost"))) is None


def test_phone_rejects_non_ascii_digits():
    """Unicode-цифры давали «валидный» номер — вторую запись для того же человека."""
    from app.schemas.user import try_normalize_phone

    assert try_normalize_phone("+7٩١٢٣٤٥٦٧٨٩") is None
    assert try_normalize_phone("8 912 345-67-89") == "+79123456789"


async def test_salon_with_blank_name_does_not_break_the_panel(client, db_session):
    """Пустое название салона: name[0] → IndexError → 500 на вкладках панели."""
    h, sid = await _owner_with_salon(db_session)
    async with db_session() as db:
        salon = await db.get(Salon, sid)
        salon.name = ""
        await db.commit()
    client.headers.update(h)
    client.cookies.set("access_token", h["Authorization"].split()[1])
    for tab in ("employees", "edit", "overview"):
        r = await client.get(f"/business/dashboard?tab={tab}")
        assert r.status_code == 200, f"{tab}: {r.status_code}"


def test_initial_handles_blank_names():
    from app.web.components.escaping import initial

    assert initial("") == "•" and initial("   ") == "•" and initial(None) == "•"
    assert initial("  анна") == "А"
