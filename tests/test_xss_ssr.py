"""XSS в серверных шаблонах (ре-тест QA X1).

Первый фикс закрыл только клиентский JS, а страницы собираются f-строками на
сервере — там имена оставались сырыми. Публичная карточка салона исполняла
пейлоад у КАЖДОГО анонима, а клиент мог сменить своё ФИО и атаковать владельца
в панели. Тесты бьют по реальным страницам и требуют, чтобы сырого тега в
ответе не было.
"""
import html
import re
from datetime import datetime, timedelta, timezone

import pytest

from app.core.security import get_password_hash
from app.models.models import (
    Booking, BookingStatus, Master, Salon, SalonMember, SalonModerationStatus,
    SalonRole, SalonSubscriptionStatus, Service, User, UserRole,
)

PAYLOAD = '<img src=x onerror=window.__pwn=1>'
# Опасен именно СЫРОЙ открывающий тег: подстрока «onerror=…» безобидно
# встречается и внутри экранированного текста (&lt;img … onerror=…&gt;).
RAW_MARKERS = ("<img src=x", "<svg onload=")


def _assert_no_raw_payload(html: str, where: str):
    for marker in RAW_MARKERS:
        assert marker not in html, f"{where}: сырой пейлоад в ответе ({marker})"
    # и текст при этом остаётся видимым — в экранированном виде
    assert "&lt;img" in html, f"{where}: имя не отрендерилось вовсе"


async def _make_salon(db_session, *, salon_name, master_name, spec, service_name):
    async with db_session() as db:
        owner = User(phone="+79997770101", full_name="Вл",
                     hashed_password=get_password_hash("Bizpass1"), role=UserRole.BUSINESS)
        muser = User(phone="+79997770102", full_name=master_name,
                     hashed_password=get_password_hash("Testpass1"), role=UserRole.MASTER)
        db.add_all([owner, muser])
        await db.commit()
        await db.refresh(owner); await db.refresh(muser)

        salon = Salon(name=salon_name, description="", address="Томск, ул. 1",
                      latitude=56.5, longitude=84.9, phone="+79990001111", city="Томск",
                      is_active=True, creator_id=owner.id,
                      moderation_status=SalonModerationStatus.APPROVED,
                      subscription_status=SalonSubscriptionStatus.ACTIVE,
                      access_until=datetime.now(timezone.utc) + timedelta(days=30))
        db.add(salon)
        await db.commit(); await db.refresh(salon)
        db.add(SalonMember(salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER,
                           is_creator=True, permissions={"manage_salon": True}, is_active=True))

        master = Master(user_id=muser.id, salon_id=salon.id, specialization=spec, is_active=True)
        db.add(master)
        await db.commit(); await db.refresh(master)

        db.add(Service(master_id=master.id, name=service_name, price=1000,
                       duration_minutes=60, is_active=True))
        await db.commit()
        return salon.id, master.id, owner.id


async def test_public_salon_page_escapes_master_and_service(client, db_session):
    """Самое срочное: аноним открывает карточку салона — пейлоад в имени
    мастера/услуги не должен исполниться."""
    sid, _mid, _oid = await _make_salon(
        db_session,
        salon_name=f"Салон{PAYLOAD}",
        master_name=f"Мастер{PAYLOAD}",
        spec=f"Спец{PAYLOAD}",
        service_name=f"Услуга{PAYLOAD}",
    )
    r = await client.get(f"/salons/{sid}")          # без авторизации
    assert r.status_code == 200
    _assert_no_raw_payload(r.text, "публичная карточка салона")


async def test_public_catalog_escapes_salon_name(client, db_session):
    await _make_salon(db_session, salon_name=f"Каталог{PAYLOAD}",
                      master_name="М", spec="с", service_name="у")
    r = await client.get("/salons")
    assert r.status_code == 200
    _assert_no_raw_payload(r.text, "каталог")


async def test_employees_tab_escapes_the_name_inside_onclick(client, db_session):
    """Вкладка «Сотрудники»: имя и специализация мастера уходят в onclick.

    Здесь опасен не тег, а АПОСТРОФ: внутри атрибута onclick="...'имя'..."
    html-экранирования мало — браузер раскодирует &#x27; обратно в апостроф,
    JS-строка закрывается и дальше идёт код. Имя и специализацию задаёт сам
    мастер через свой профиль, то есть сотрудник мог атаковать владельца.
    Поэтому значения собираются ejs() (JSON-литерал + экранирование).
    """
    breakout = "');window.__pwn=1;//"
    sid, _mid, _oid = await _make_salon(
        db_session, salon_name="Салон",
        master_name=f"Мастер{PAYLOAD}{breakout}", spec=f"Спец{breakout}",
        service_name="Услуга",
    )
    await client.post("/api/v1/auth/login-web",
                      data={"phone": "+79997770101", "password": "Bizpass1"})

    r = await client.get(f"/business/dashboard?salon_id={sid}&tab=employees")
    assert r.status_code == 200
    _assert_no_raw_payload(r.text, "вкладка «Сотрудники»")

    # Проверять исходник страницы здесь мало: html.escape прячет апостроф как
    # &#x27;, в тексте его не видно, а браузер перед разбором JS раскодирует
    # атрибут обратно. Поэтому смотрим onclick ПОСЛЕ раскодирования.
    onclicks = [html.unescape(m) for m in re.findall(r'onclick="([^"]*)"', r.text)]
    calls = [c for c in onclicks if "Employee(" in c and "__pwn" in c]
    assert calls, "кнопок с именем мастера на вкладке не нашлось"
    for call in calls:
        assert "'Мастер" not in call, (
            f"имя передано JS-строкой в апострофах, а в нём апостроф: {call}"
        )
        assert '"Мастер' in call, f"имя должно быть JSON-литералом: {call}"


async def test_guest_booking_page_escapes_names(client, db_session):
    """Гостевая запись отдаёт мастеров и услуги JSON-ом в data-атрибуте:
    апостроф/кавычка в имени не должны закрывать атрибут."""
    sid, _mid, _oid = await _make_salon(
        db_session, salon_name=f"Гость{PAYLOAD}",
        master_name=f"М{PAYLOAD}", spec="с", service_name=f"У{PAYLOAD}",
    )
    async with db_session() as db:
        salon = await db.get(Salon, sid)
        salon.published_at = datetime.now(timezone.utc)
        salon.guest_booking_enabled = True
        await db.commit()
    r = await client.get(f"/book/{sid}")
    assert r.status_code == 200
    _assert_no_raw_payload(r.text, "гостевая запись")
