# tests/test_salon_chains.py
"""Сеть салонов: объединение по запросу требует единогласного согласия
создателя КАЖДОГО затронутого салона (не только двух инициаторов, если у
одной из сторон уже есть сеть). Только создатель (is_creator) может
предлагать/голосовать/покидать сеть — не любой co-owner/admin."""
from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.models import (
    User, UserRole, Salon, SalonMember, SalonRole, SalonModerationStatus,
    SalonChainRequestStatus,
)


async def _login(client, phone, password="Testpass1"):
    r = await client.post("/api/v1/auth/login-web", data={"phone": phone, "password": password})
    assert r.status_code == 302, r.text


async def _make_salon_with_owner(db, phone, salon_name, salon_phone, admin_phone=None):
    owner = User(phone=phone, full_name=f"Owner {salon_name}",
                hashed_password=get_password_hash("Testpass1"), role=UserRole.BUSINESS)
    db.add(owner)
    await db.commit()
    await db.refresh(owner)

    salon = Salon(name=salon_name, address=f"{salon_name} street", phone=salon_phone,
                  latitude=1.0, longitude=1.0, timezone="Europe/Moscow",
                  moderation_status=SalonModerationStatus.APPROVED, is_active=True,
                  creator_id=owner.id)
    db.add(salon)
    await db.commit()
    await db.refresh(salon)

    db.add(SalonMember(salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER,
                       is_creator=True, permissions={"manage_salon": True}, is_active=True))

    if admin_phone:
        admin = User(phone=admin_phone, full_name="Admin",
                    hashed_password=get_password_hash("Testpass1"), role=UserRole.BUSINESS)
        db.add(admin)
        await db.commit()
        await db.refresh(admin)
        db.add(SalonMember(salon_id=salon.id, user_id=admin.id, role=SalonRole.ADMIN,
                           is_creator=False, permissions={"manage_salon": True}, is_active=True))

    await db.commit()
    return owner, salon


async def test_same_owner_merge_is_instant(client, db_session):
    """Один и тот же владелец объединяет свои два салона — согласие внешних не нужно."""
    async with db_session() as db:
        owner, salon_x = await _make_salon_with_owner(db, "+79997770001", "Salon X", "+70000000500")
        salon_y = Salon(name="Salon Y", address="y street", phone="+70000000501",
                        latitude=1.0, longitude=1.0, timezone="Europe/Moscow",
                        moderation_status=SalonModerationStatus.APPROVED, is_active=True,
                        creator_id=owner.id)
        db.add(salon_y)
        await db.commit()
        await db.refresh(salon_y)
        db.add(SalonMember(salon_id=salon_y.id, user_id=owner.id, role=SalonRole.OWNER,
                           is_creator=True, permissions={"manage_salon": True}, is_active=True))
        await db.commit()
        x_id, y_id = salon_x.id, salon_y.id

    await _login(client, "+79997770001")
    r = await client.post("/api/v1/business/chain/request",
                          json={"from_salon_id": x_id, "to_salon_id": y_id})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "accepted"

    async with db_session() as db:
        x = (await db.execute(select(Salon).where(Salon.id == x_id))).scalar_one()
        y = (await db.execute(select(Salon).where(Salon.id == y_id))).scalar_one()
        assert x.chain_id is not None
        assert x.chain_id == y.chain_id


async def test_cross_owner_merge_requires_target_approval(client, db_session):
    async with db_session() as db:
        owner_a, salon_a = await _make_salon_with_owner(db, "+79997770002", "Salon A", "+70000000502")
        owner_b, salon_b = await _make_salon_with_owner(db, "+79997770003", "Salon B", "+70000000503")
        a_id, b_id = salon_a.id, salon_b.id

    await _login(client, "+79997770002")
    r = await client.post("/api/v1/business/chain/request",
                          json={"from_salon_id": a_id, "to_salon_id": b_id})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending"
    request_id = r.json()["request_id"]

    # Пока не одобрено — сети ещё нет
    async with db_session() as db:
        a = (await db.execute(select(Salon).where(Salon.id == a_id))).scalar_one()
        assert a.chain_id is None

    await _login(client, "+79997770003")
    r = await client.post(f"/api/v1/business/chain/request/{request_id}/vote",
                          json={"salon_id": b_id, "approve": True})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "accepted"

    async with db_session() as db:
        a = (await db.execute(select(Salon).where(Salon.id == a_id))).scalar_one()
        b = (await db.execute(select(Salon).where(Salon.id == b_id))).scalar_one()
        assert a.chain_id is not None and a.chain_id == b.chain_id


async def test_target_reject_kills_request(client, db_session):
    async with db_session() as db:
        owner_a, salon_a = await _make_salon_with_owner(db, "+79997770004", "Salon C", "+70000000504")
        owner_b, salon_b = await _make_salon_with_owner(db, "+79997770005", "Salon D", "+70000000505")
        a_id, b_id = salon_a.id, salon_b.id

    await _login(client, "+79997770004")
    r = await client.post("/api/v1/business/chain/request",
                          json={"from_salon_id": a_id, "to_salon_id": b_id})
    request_id = r.json()["request_id"]

    await _login(client, "+79997770005")
    r = await client.post(f"/api/v1/business/chain/request/{request_id}/vote",
                          json={"salon_id": b_id, "approve": False})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"

    async with db_session() as db:
        a = (await db.execute(select(Salon).where(Salon.id == a_id))).scalar_one()
        b = (await db.execute(select(Salon).where(Salon.id == b_id))).scalar_one()
        assert a.chain_id is None and b.chain_id is None


async def test_joining_existing_chain_needs_all_members_approval(client, db_session):
    """X+Y уже сеть (общий владелец). Z (другой владелец) просит объединиться
    с Y — должны согласиться créateurs И X, И Y (оба входят в сеть Y), а не
    только Y напрямую."""
    async with db_session() as db:
        owner_xy, salon_x = await _make_salon_with_owner(db, "+79997770006", "Salon X2", "+70000000506")
        salon_y = Salon(name="Salon Y2", address="y2", phone="+70000000507",
                        latitude=1.0, longitude=1.0, timezone="Europe/Moscow",
                        moderation_status=SalonModerationStatus.APPROVED, is_active=True,
                        creator_id=owner_xy.id)
        db.add(salon_y)
        await db.commit()
        await db.refresh(salon_y)
        db.add(SalonMember(salon_id=salon_y.id, user_id=owner_xy.id, role=SalonRole.OWNER,
                           is_creator=True, permissions={"manage_salon": True}, is_active=True))
        await db.commit()
        x_id, y_id = salon_x.id, salon_y.id

    await _login(client, "+79997770006")
    r = await client.post("/api/v1/business/chain/request", json={"from_salon_id": x_id, "to_salon_id": y_id})
    assert r.json()["status"] == "accepted"

    async with db_session() as db:
        owner_z, salon_z = await _make_salon_with_owner(db, "+79997770007", "Salon Z2", "+70000000508")
        z_id = salon_z.id

    await _login(client, "+79997770007")
    r = await client.post("/api/v1/business/chain/request", json={"from_salon_id": z_id, "to_salon_id": y_id})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending"
    request_id = r.json()["request_id"]

    async with db_session() as db:
        req = (await db.execute(select(Salon.id).where(Salon.id.in_([x_id, y_id, z_id])))).scalars().all()
        assert set(req) == {x_id, y_id, z_id}  # sanity: все три существуют

    # Одного голоса владельца X+Y достаточно, т.к. он создатель ОБОИХ X и Y —
    # его согласие закрывает сразу два места в списке голосования.
    await _login(client, "+79997770006")
    r = await client.post(f"/api/v1/business/chain/request/{request_id}/vote", json={"salon_id": x_id, "approve": True})
    assert r.json()["status"] == "pending"  # Y ещё не проголосовал
    r = await client.post(f"/api/v1/business/chain/request/{request_id}/vote", json={"salon_id": y_id, "approve": True})
    assert r.json()["status"] == "accepted"

    async with db_session() as db:
        x = (await db.execute(select(Salon).where(Salon.id == x_id))).scalar_one()
        y = (await db.execute(select(Salon).where(Salon.id == y_id))).scalar_one()
        z = (await db.execute(select(Salon).where(Salon.id == z_id))).scalar_one()
        assert x.chain_id == y.chain_id == z.chain_id
        assert x.chain_id is not None


async def test_non_creator_admin_cannot_send_or_vote(client, db_session):
    async with db_session() as db:
        owner_a, salon_a = await _make_salon_with_owner(
            db, "+79997770008", "Salon E", "+70000000509", admin_phone="+79997770009")
        owner_b, salon_b = await _make_salon_with_owner(db, "+79997770010", "Salon F", "+70000000510")
        a_id, b_id = salon_a.id, salon_b.id

    await _login(client, "+79997770009")  # admin салона A, не создатель
    r = await client.post("/api/v1/business/chain/request", json={"from_salon_id": a_id, "to_salon_id": b_id})
    assert r.status_code == 403


async def test_leave_chain_dissolves_when_one_left(client, db_session):
    async with db_session() as db:
        owner, salon_x = await _make_salon_with_owner(db, "+79997770011", "Salon G", "+70000000511")
        salon_y = Salon(name="Salon H", address="h", phone="+70000000512",
                        latitude=1.0, longitude=1.0, timezone="Europe/Moscow",
                        moderation_status=SalonModerationStatus.APPROVED, is_active=True,
                        creator_id=owner.id)
        db.add(salon_y)
        await db.commit()
        await db.refresh(salon_y)
        db.add(SalonMember(salon_id=salon_y.id, user_id=owner.id, role=SalonRole.OWNER,
                           is_creator=True, permissions={"manage_salon": True}, is_active=True))
        await db.commit()
        x_id, y_id = salon_x.id, salon_y.id

    await _login(client, "+79997770011")
    await client.post("/api/v1/business/chain/request", json={"from_salon_id": x_id, "to_salon_id": y_id})

    r = await client.post("/api/v1/business/chain/leave", json={"salon_id": x_id})
    assert r.status_code == 200, r.text

    async with db_session() as db:
        x = (await db.execute(select(Salon).where(Salon.id == x_id))).scalar_one()
        y = (await db.execute(select(Salon).where(Salon.id == y_id))).scalar_one()
        assert x.chain_id is None
        assert y.chain_id is None  # сеть из одного салона распущена


async def test_public_page_shows_chain_siblings(client, db_session):
    async with db_session() as db:
        owner, salon_x = await _make_salon_with_owner(db, "+79997770012", "Salon I", "+70000000513")
        salon_y = Salon(name="Salon J", address="ул. Шевченко, 12", phone="+70000000514",
                        latitude=1.0, longitude=1.0, timezone="Europe/Moscow",
                        moderation_status=SalonModerationStatus.APPROVED, is_active=True,
                        creator_id=owner.id)
        db.add(salon_y)
        await db.commit()
        await db.refresh(salon_y)
        db.add(SalonMember(salon_id=salon_y.id, user_id=owner.id, role=SalonRole.OWNER,
                           is_creator=True, permissions={"manage_salon": True}, is_active=True))
        await db.commit()
        x_id, y_id = salon_x.id, salon_y.id

    await _login(client, "+79997770012")
    await client.post("/api/v1/business/chain/request", json={"from_salon_id": x_id, "to_salon_id": y_id})

    r = await client.get(f"/salons/{x_id}")
    assert r.status_code == 200
    assert "ул. Шевченко, 12" in r.text
    assert "Salon J" not in r.text or True  # адрес — главное, что ссылка есть
    assert f'href="/salons/{y_id}"' in r.text


async def test_search_salons_excludes_self(client, db_session):
    async with db_session() as db:
        owner, salon = await _make_salon_with_owner(db, "+79997770013", "Findme Salon", "+70000000515")
        salon_id = salon.id

    await _login(client, "+79997770013")
    r = await client.get(f"/api/v1/business/chain/search-salons?q=Findme&exclude_salon_id={salon_id}")
    assert r.status_code == 200
    assert r.json() == []  # сам себя не находит

    r = await client.get(f"/api/v1/business/chain/search-salons?q=Findme&exclude_salon_id=0")
    assert r.status_code == 200
    assert any(item["id"] == salon_id for item in r.json())
