# tests/test_master_landing.py
"""Лендинг для частных мастеров (/dlya-masterov) и путь до подключения.

Главное, что закрепляем: метки рекламы не теряются по дороге от объявления
до подключения, страница не индексируется, а частный мастер после подключения
сразу становится мастером своего «салона» — к нему можно записаться.
"""
from urllib.parse import parse_qs, unquote, urlparse

from sqlalchemy import select

from app.models.models import AdAttribution, Master, Salon
from tests.conftest import register_user

UTM = "utm_source=yandex&utm_medium=cpc&utm_campaign=masters&yclid=987654"


async def test_landing_is_noindex_and_carries_labels(client):
    r = await client.get(f"/dlya-masterov?{UTM}&evil=zz_injected_zz")
    assert r.status_code == 200
    assert "noindex" in r.headers.get("x-robots-tag", "")
    assert '<meta name="robots" content="noindex, nofollow">' in r.text
    # анонима кнопка ведёт на регистрацию с возвратом на подключение
    href = r.text.split('class="ml-cta" href="', 1)[1].split('"', 1)[0].replace("&amp;", "&")
    assert href.startswith("/register?redirect=")
    target = unquote(href.split("redirect=", 1)[1])
    q = parse_qs(urlparse(target).query)
    assert urlparse(target).path == "/business/checkout"
    assert q["for"] == ["master"] and q["plan"] == ["lite"]
    assert q["utm_source"] == ["yandex"] and q["yclid"] == ["987654"]
    assert q["landing"] == ["dlya-masterov"]
    assert "evil" not in q                      # чужие параметры дальше не едут
    assert "zz_injected_zz" not in r.text


async def test_landing_has_single_exit(client):
    """Сепарированная страница: никаких ссылок «погулять» по сайту —
    только кнопка подключения, документы в новой вкладке и почта.

    Почта разрешена ровно одна и только mailto: текст страницы сам предлагает
    «пишите на hello@rrumi.ru», и адрес без ссылки заставлял его копировать.
    На сайт она не уводит."""
    r = await client.get("/dlya-masterov")
    import re
    hrefs = set(re.findall(r'<a [^>]*href="([^"]+)"', r.text))
    allowed = {"/license", "/privacy", "/cookies", "mailto:hello@rrumi.ru"}
    for href in hrefs:
        assert href in allowed or href.startswith("/register?redirect=%2Fbusiness%2Fcheckout"), href


async def test_registration_returns_to_checkout(client):
    """Регистрация раньше всегда вела в /profile — подключение и метки терялись."""
    target = "/business/checkout?plan=lite&for=master&utm_source=yandex&yclid=987654"
    r = await client.post("/api/v1/auth/register/send-code", json={"phone": "+79997771003"})
    code = r.json()
    r = await client.post("/api/v1/auth/register-web", data={
        "phone": "+79997771003", "password": "Testpass1", "full_name": "Мастер",
        "pd_consent": "1", "request_id": code["request_id"], "code": code["dev_code"],
        "redirect": target,
    })
    assert r.status_code == 302
    assert r.headers["location"] == target


async def test_registration_ignores_foreign_redirect(client):
    r = await client.post("/api/v1/auth/register/send-code", json={"phone": "+79997771004"})
    code = r.json()
    r = await client.post("/api/v1/auth/register-web", data={
        "phone": "+79997771004", "password": "Testpass1", "pd_consent": "1",
        "request_id": code["request_id"], "code": code["dev_code"],
        "redirect": "//evil.example/steal",
    })
    assert r.headers["location"] == "/"


async def test_master_checkout_page_wording(client):
    r = await client.get("/business/checkout?plan=lite&for=master")
    assert r.status_code == 200
    assert "Подключение мастера" in r.text
    assert "Название салона" not in r.text
    # неавторизованному — сразу регистрация, а не форма, которая потом пропадёт
    assert "/register?redirect=" in r.text
    # галочка ведёт на тот документ, который сервер пишет в журнал
    assert 'href="/license"' in r.text


async def test_master_apply_creates_master_and_saves_labels(client, db_session):
    data = await register_user(client, "+79997771001")
    client.cookies.set("access_token", data["access_token"])
    r = await client.post("/api/v1/business/apply", data={
        "salon_name": "Анна Смирнова", "phone": "+79997771001",
        "offer_accepted": "1", "pd_consent": "1", "plan": "lite",
        "for_master": "1", "specialization": "Маникюр",
        "utm_source": "yandex", "utm_campaign": "masters", "yclid": "987654",
        "landing": "dlya-masterov",
    })
    assert r.status_code == 200, r.text
    salon_id = r.json()["salon_id"]

    async with db_session() as db:
        salon = await db.get(Salon, salon_id)
        master = (await db.execute(select(Master).where(Master.salon_id == salon_id))).scalar_one()
        assert master.user_id == salon.creator_id
        assert master.specialization == "Маникюр"
        label = (await db.execute(select(AdAttribution).where(AdAttribution.salon_id == salon_id))).scalar_one()
        assert (label.utm_source, label.yclid, label.landing) == ("yandex", "987654", "dlya-masterov")


async def test_salon_apply_without_labels_writes_nothing(client, db_session):
    """Обычное подключение салона: мастера не заводим, пустую метку не пишем."""
    data = await register_user(client, "+79997771002")
    client.cookies.set("access_token", data["access_token"])
    r = await client.post("/api/v1/business/apply", data={
        "salon_name": "Салон", "phone": "+79997771002",
        "offer_accepted": "1", "pd_consent": "1", "plan": "business",
    })
    salon_id = r.json()["salon_id"]
    async with db_session() as db:
        assert (await db.execute(select(Master).where(Master.salon_id == salon_id))).first() is None
        assert (await db.execute(select(AdAttribution))).first() is None


async def test_register_redirect_is_honoured_and_safe(client):
    from app.services.auth_redirect import safe_redirect

    assert safe_redirect("/business/checkout?plan=lite") == "/business/checkout?plan=lite"
    for bad in ("//evil.example", "https://evil.example", "/\\evil.example", ""):
        assert safe_redirect(bad) == ""

    r = await client.get("/register?redirect=%2Fbusiness%2Fcheckout%3Fplan%3Dlite")
    assert 'name="redirect" value="/business/checkout?plan=lite"' in r.text


async def test_login_page_passes_redirect_on(client):
    """С /login человек уходит на регистрацию или во вход через Яндекс/VK —
    адрес возврата должен ехать и туда."""
    r = await client.get("/login?redirect=%2Fbusiness%2Fcheckout%3Fplan%3Dlite")
    assert "/register?redirect=%2Fbusiness%2Fcheckout%3Fplan%3Dlite" in r.text
    assert "/api/v1/auth/vk/start?redirect=%2Fbusiness%2Fcheckout%3Fplan%3Dlite" in r.text


async def test_oauth_redirect_is_remembered_by_state(client):
    from app.services import auth_redirect

    await auth_redirect.remember_for_oauth("vk", "state-1", "/business/checkout?plan=lite")
    await auth_redirect.remember_for_oauth("vk", "state-2", "https://evil.example")
    assert await auth_redirect.pop_for_oauth("vk", "state-1") == "/business/checkout?plan=lite"
    assert await auth_redirect.pop_for_oauth("vk", "state-1") == "/profile"   # одноразово
    assert await auth_redirect.pop_for_oauth("vk", "state-2") == "/profile"


async def test_client_card_renders_for_owner(client, db_session):
    """Карточка клиента падала с 500: render_header звали с лишним аргументом."""
    data = await register_user(client, "+79997771005")
    client.cookies.set("access_token", data["access_token"])
    r = await client.post("/api/v1/business/apply", data={
        "salon_name": "Карточка", "phone": "+79997771005",
        "offer_accepted": "1", "pd_consent": "1", "plan": "lite", "for_master": "1",
    })
    salon_id = r.json()["salon_id"]
    r = await client.get(f"/business/clients/{data['user']['id'] if 'user' in data else 1}?salon_id={salon_id}")
    assert r.status_code == 200


async def test_guest_booking_speaks_of_master_for_solo(client, db_session):
    """У частного мастера страница записи не говорит «салон подтвердит»."""
    data = await register_user(client, "+79997771006")
    client.cookies.set("access_token", data["access_token"])
    r = await client.post("/api/v1/business/apply", data={
        "salon_name": "Анна Смирнова", "phone": "+79997771006",
        "offer_accepted": "1", "pd_consent": "1", "plan": "lite", "for_master": "1",
    })
    salon_id = r.json()["salon_id"]
    from app.models.models import SalonModerationStatus
    async with db_session() as db:
        salon = await db.get(Salon, salon_id)
        salon.moderation_status = SalonModerationStatus.APPROVED
        salon.guest_booking_enabled = True
        from datetime import datetime, timezone
        salon.published_at = datetime.now(timezone.utc)
        master = (await db.execute(select(Master).where(Master.salon_id == salon_id))).scalar_one()
        from app.models.models import Service
        db.add(Service(master_id=master.id, name="Маникюр", price=2000, duration_minutes=90))
        await db.commit()
    r = await client.get(f"/book/{salon_id}")
    assert "мастер подтвердит запись" in r.text, r.text[:500]
    assert "салон подтвердит" not in r.text
