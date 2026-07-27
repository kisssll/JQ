"""Smoke-тест ВСЕХ веб-страниц: ни одна не должна отдавать 500.

Проверяем три среза:
- публичные страницы (аноним) — рендерятся;
- защищённые (аноним) — редирект/4xx, но не падение;
- защищённые под реальной ролью (владелец/мастер/модель/админ) с посеянными
  данными — рендерятся на непустом салоне/мастере/модели.

Плюс параметрические страницы с реальными id и с несуществующими (404, не 500).
Цель — ловить падения рендера страниц до прода, а не в бою.
"""
from datetime import datetime, timedelta

from app.core.security import get_password_hash
from app.models.models import (
    User, UserRole, Salon, SalonMember, SalonRole, Master, Service, Booking,
    BookingStatus, SalonModerationStatus, ModelModerationStatus,
)

PUBLIC_PAGES = [
    "/", "/salons", "/business", "/login", "/register", "/about",
    "/forgot-password", "/reset-password", "/offline", "/model", "/book",
    "/robots.txt", "/sitemap.xml", "/logout", "/definitely-no-such-page-xyz",
]

PROTECTED_PAGES = [
    "/profile", "/bookings", "/favorites", "/business/dashboard",
    "/business/register-salon", "/business/my-salon", "/business/checkout",
    "/master/dashboard", "/master/inventory", "/model/dashboard", "/model/join",
    "/admin",
]

ADMIN_PHONE = "+79990000001"
OWNER_PHONE = "+79990000002"
MASTER_PHONE = "+79990000003"
MODEL_PHONE = "+79990000005"


async def _seed(db) -> dict:
    admin = User(phone=ADMIN_PHONE, full_name="Admin", hashed_password=get_password_hash("Testpass1"),
                 role=UserRole.ADMIN, is_active=True)
    owner = User(phone=OWNER_PHONE, full_name="Owner", hashed_password=get_password_hash("Testpass1"),
                 role=UserRole.BUSINESS, is_active=True)
    muser = User(phone=MASTER_PHONE, full_name="Master", hashed_password=get_password_hash("Testpass1"),
                 role=UserRole.BUSINESS, is_active=True)
    client_u = User(phone="+79990000004", full_name="Client", hashed_password=get_password_hash("Testpass1"),
                    role=UserRole.CLIENT, is_active=True)
    model_u = User(phone=MODEL_PHONE, full_name="Model", hashed_password=get_password_hash("Testpass1"),
                   role=UserRole.CLIENT, is_active=True, is_model=True,
                   model_moderation_status=ModelModerationStatus.APPROVED)
    db.add_all([admin, owner, muser, client_u, model_u])
    await db.commit()
    for u in (owner, muser, client_u):
        await db.refresh(u)

    salon = Salon(name="Smoke Salon", address="ул. Тестовая, 1", phone="+70000000901",
                  latitude=1.0, longitude=1.0, timezone="Europe/Moscow",
                  moderation_status=SalonModerationStatus.APPROVED, is_active=True, creator_id=owner.id)
    db.add(salon)
    await db.commit()
    await db.refresh(salon)

    db.add(SalonMember(salon_id=salon.id, user_id=owner.id, role=SalonRole.OWNER,
                       is_creator=True, permissions={}, is_active=True))
    await db.commit()

    master = Master(salon_id=salon.id, user_id=muser.id, specialization="Барбер")
    db.add(master)
    await db.commit()
    await db.refresh(master)

    svc = Service(master_id=master.id, name="Стрижка", price=1000, duration_minutes=60)
    db.add(svc)
    await db.commit()
    await db.refresh(svc)

    now = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    db.add(Booking(client_id=client_u.id, master_id=master.id, service_id=svc.id,
                   start_time=now + timedelta(days=1), end_time=now + timedelta(days=1, hours=1),
                   status=BookingStatus.CONFIRMED, final_price=1000))
    await db.commit()

    return {"salon": salon.id, "master": master.id, "client": client_u.id}


def _assert_ok(r, where):
    assert r.status_code < 500, f"{where} -> {r.status_code}: {r.text[:400]}"


async def test_public_and_param_pages_no_500(client, db_session):
    async with db_session() as db:
        ids = await _seed(db)

    for path in PUBLIC_PAGES:
        _assert_ok(await client.get(path), f"public {path}")

    for path in (f"/salons/{ids['salon']}", f"/masters/{ids['master']}",
                 f"/book/{ids['salon']}", f"/salons/{ids['salon']}/book"):
        _assert_ok(await client.get(path), f"param {path}")

    # Несуществующие сущности → 404, не 500
    for path in ("/salons/99999", "/masters/99999", "/book/99999", "/business/clients/99999"):
        _assert_ok(await client.get(path), f"missing {path}")


async def test_protected_pages_unauth_no_500(client, db_session):
    async with db_session() as db:
        await _seed(db)
    for path in PROTECTED_PAGES:
        _assert_ok(await client.get(path), f"unauth {path}")


async def _login(client, phone):
    r = await client.post("/api/v1/auth/login-web", data={"phone": phone, "password": "Testpass1"})
    assert r.status_code == 302, r.text


async def test_protected_pages_authed_no_500(client, db_session):
    async with db_session() as db:
        await _seed(db)

    await _login(client, OWNER_PHONE)
    for path in ("/business/dashboard", "/business/my-salon", "/profile", "/bookings",
                 "/favorites", "/business/checkout", "/business/register-salon"):
        _assert_ok(await client.get(path), f"owner {path}")

    await _login(client, MASTER_PHONE)
    for path in ("/master/dashboard", "/master/inventory", "/business/dashboard"):
        _assert_ok(await client.get(path), f"master {path}")

    await _login(client, MODEL_PHONE)
    for path in ("/model/dashboard", "/model/join", "/model", "/profile"):
        _assert_ok(await client.get(path), f"model {path}")

    await _login(client, ADMIN_PHONE)
    _assert_ok(await client.get("/admin"), "admin /admin")
