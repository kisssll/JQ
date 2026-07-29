# tests/test_salon_geocoding.py
"""Координаты салона обязательны из подсказок Яндекса, когда на сервере
задан YANDEX_MAPS_API_KEY — без ключа (дефолт в тестах/локальной
разработке) поведение прежнее (координаты не обязательны, дефолтная точка).
См. app/api/v1/endpoints/business.py::create_or_update_salon/update_my_salon."""
from sqlalchemy import select

from app.core.config import settings
from app.models.models import Salon
from tests.conftest import register_user


async def _create_salon_owner(client, phone):
    data = await register_user(client, phone)
    client.cookies.set("access_token", data["access_token"])


async def test_create_without_key_uses_default_coords(client, db_session):
    """Без ключа (обычный тестовый режим) — старое поведение, координаты не обязательны."""
    await _create_salon_owner(client, "+79997770001")
    r = await client.post("/api/v1/business/my-salon", data={
        "name": "Без геокодера", "address": "Новосибирск, ул. Ленина, 1",
        "phone": "+79991110001", "offer_accepted": "1",
    })
    assert r.status_code in (302, 303)
    async with db_session() as db:
        s = (await db.execute(select(Salon).where(Salon.name == "Без геокодера"))).scalar_one()
        assert s.latitude == 55.7558 and s.longitude == 37.6173


async def test_create_with_key_requires_coords(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "YANDEX_MAPS_API_KEY", "test-key")
    await _create_salon_owner(client, "+79997770002")
    r = await client.post("/api/v1/business/my-salon", data={
        "name": "Без координат", "address": "Новосибирск, ул. Мира, 2",
        "phone": "+79991110002", "offer_accepted": "1",
    })
    assert r.status_code == 400
    assert "подсказок" in r.text
    async with db_session() as db:
        s = (await db.execute(select(Salon).where(Salon.name == "Без координат"))).scalar_one_or_none()
        assert s is None


async def test_create_with_key_and_coords_succeeds(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "YANDEX_MAPS_API_KEY", "test-key")
    await _create_salon_owner(client, "+79997770003")
    r = await client.post("/api/v1/business/my-salon", data={
        "name": "С координатами", "address": "Новосибирск, ул. Кирова, 3",
        "phone": "+79991110003", "offer_accepted": "1",
        "latitude": "55.0084", "longitude": "82.9357",
    })
    assert r.status_code in (302, 303), r.text
    async with db_session() as db:
        s = (await db.execute(select(Salon).where(Salon.name == "С координатами"))).scalar_one()
        assert abs(s.latitude - 55.0084) < 1e-6
        assert abs(s.longitude - 82.9357) < 1e-6


async def test_create_with_key_rejects_out_of_range_coords(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "YANDEX_MAPS_API_KEY", "test-key")
    await _create_salon_owner(client, "+79997770004")
    r = await client.post("/api/v1/business/my-salon", data={
        "name": "Кривые координаты", "address": "Новосибирск, ул. Гоголя, 4",
        "phone": "+79991110004", "offer_accepted": "1",
        "latitude": "999", "longitude": "82.9357",
    })
    assert r.status_code == 400


async def test_update_address_change_requires_coords(client, db_session, monkeypatch):
    await _create_salon_owner(client, "+79997770005")
    r = await client.post("/api/v1/business/my-salon", data={
        "name": "Салон для правки", "address": "Новосибирск, ул. Первая, 5",
        "phone": "+79991110005", "offer_accepted": "1",
    })
    assert r.status_code in (302, 303)
    async with db_session() as db:
        salon_id = (await db.execute(select(Salon.id).where(Salon.name == "Салон для правки"))).scalar_one()

    monkeypatch.setattr(settings, "YANDEX_MAPS_API_KEY", "test-key")
    r = await client.put(f"/api/v1/business/my-salon?salon_id={salon_id}",
                         json={"address": "Новосибирск, ул. Вторая, 6"})
    assert r.status_code == 400
    assert "координат" in r.json()["detail"]


async def test_update_address_change_with_coords_succeeds(client, db_session, monkeypatch):
    await _create_salon_owner(client, "+79997770006")
    r = await client.post("/api/v1/business/my-salon", data={
        "name": "Салон для правки 2", "address": "Новосибирск, ул. Третья, 7",
        "phone": "+79991110006", "offer_accepted": "1",
    })
    assert r.status_code in (302, 303)
    async with db_session() as db:
        salon_id = (await db.execute(select(Salon.id).where(Salon.name == "Салон для правки 2"))).scalar_one()

    monkeypatch.setattr(settings, "YANDEX_MAPS_API_KEY", "test-key")
    r = await client.put(f"/api/v1/business/my-salon?salon_id={salon_id}", json={
        "address": "Новосибирск, ул. Четвёртая, 8",
        "latitude": 55.03, "longitude": 82.92,
    })
    assert r.status_code == 200, r.text
    async with db_session() as db:
        s = (await db.execute(select(Salon).where(Salon.id == salon_id))).scalar_one()
        assert s.address == "Новосибирск, ул. Четвёртая, 8"
        assert abs(s.latitude - 55.03) < 1e-6
        assert abs(s.longitude - 82.92) < 1e-6


async def test_update_other_fields_without_address_change_no_coords_needed(client, db_session, monkeypatch):
    await _create_salon_owner(client, "+79997770007")
    r = await client.post("/api/v1/business/my-salon", data={
        "name": "Салон для правки 3", "address": "Новосибирск, ул. Пятая, 9",
        "phone": "+79991110007", "offer_accepted": "1",
    })
    assert r.status_code in (302, 303)
    async with db_session() as db:
        salon_id = (await db.execute(select(Salon.id).where(Salon.name == "Салон для правки 3"))).scalar_one()

    monkeypatch.setattr(settings, "YANDEX_MAPS_API_KEY", "test-key")
    # Адрес не передан вообще — координаты не нужны, даже с ключом.
    r = await client.put(f"/api/v1/business/my-salon?salon_id={salon_id}", json={"phone": "+79991119999"})
    assert r.status_code == 200, r.text
