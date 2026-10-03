"""Страница записи /book/{id} после переделки формы.

Заход по подложке 03.10.2026 переписал ВИД этой страницы и ничего не менял
в её поведении. Эти проверки фиксируют поведение: те же четыре шага, те же
подписи, те же проверки и те же отказы. Если следующий заход по форме
что-нибудь уронит, падать должно здесь, а не у клиента.
"""
import re
from datetime import datetime, timedelta

from sqlalchemy import select

from app.models.models import (
    Booking, BookingStatus, Salon, SalonModerationStatus,
)
from tests.test_guest_booking import _setup, _payload


async def test_page_keeps_all_four_steps_in_order(client, db_session):
    salon_id, _, _ = await _setup(
        db_session, salon_phone="+70000000200", master_phone="+79993330200")
    r = await client.get(f"/book/{salon_id}")
    assert r.status_code == 200

    steps = re.findall(r'data-step="([a-z]+)"', r.text)
    assert steps == ["master", "service", "slot", "details", "done"]

    # Подписи шагов — те же слова, что были до переделки.
    for title in ("Выберите мастера", "Услуга", "Дата и время", "Ваши данные"):
        assert title in r.text, title

    # Счётчик шагов не должен разъехаться с самими шагами.
    assert r.text.count("из 4") == 4
    assert "Шаг 1 из 4" in r.text and "Шаг 4 из 4" in r.text


async def test_page_keeps_the_hooks_the_script_needs(client, db_session):
    """Разметку собирает сервер, а шаги листает guest-booking.js. Список
    зацепок — это договор между ними: переименовали id, и страница молча
    перестала работать, оставшись при этом красивой."""
    salon_id, _, _ = await _setup(
        db_session, salon_phone="+70000000201", master_phone="+79993330201")
    r = await client.get(f"/book/{salon_id}")
    for hook in ('id="guest-book"', 'data-salon-id', 'data-masters',
                 'id="gb-masters"', 'id="gb-services"', 'id="gb-date"',
                 'id="gb-slots"', 'id="gb-summary"', 'id="gb-name"',
                 'id="gb-phone"', 'id="gb-email"', 'id="gb-consent"',
                 'id="gb-error"', 'id="gb-submit"', 'id="gb-manage-link"',
                 'class="gb-back"'):
        assert hook in r.text, hook
    # Маска телефона вешается по классу.
    assert "phone-input" in r.text


async def test_page_still_asks_for_consent_with_the_legal_version(client, db_session):
    """Согласие на ПДн обязательно: форма собирает имя, телефон и почту.
    Версия редакции едет в data-legal-version — по ней пишется журнал."""
    salon_id, _, _ = await _setup(
        db_session, salon_phone="+70000000202", master_phone="+79993330202")
    r = await client.get(f"/book/{salon_id}")
    assert "data-legal-version=" in r.text
    assert 'id="gb-consent"' in r.text and "required" in r.text
    for link in ("/consent", "/terms", "/privacy"):
        assert f'href="{link}"' in r.text


async def test_page_is_built_on_the_shared_layer(client, db_session):
    """Показательный экран обязан быть собран набором, а не своей вёрсткой:
    иначе доказательства, что набор пригоден, нет. Инлайнового <style> на
    странице больше нет — стили уехали в бандл."""
    salon_id, _, _ = await _setup(
        db_session, salon_phone="+70000000203", master_phone="+79993330203")
    r = await client.get(f"/book/{salon_id}")
    assert "<style>" not in r.text
    for cls in ("r-btn r-btn--primary", "r-field", "r-input", "r-display"):
        assert cls in r.text, cls


async def test_refusal_when_guest_booking_is_switched_off(client, db_session):
    salon_id, _, _ = await _setup(
        db_session, salon_phone="+70000000204", master_phone="+79993330204",
        guest_enabled=False)
    r = await client.get(f"/book/{salon_id}")
    assert r.status_code == 200
    assert "Запись недоступна" in r.text
    assert 'id="guest-book"' not in r.text
    # Отказ даёт следующий шаг, а не тупик.
    assert 'href="/"' in r.text


async def test_refusal_when_salon_is_not_published(client, db_session):
    """published_at = NULL — салон одобрен модерацией, но владелец его ещё
    не опубликовал. Записывать к нему нельзя."""
    salon_id, _, _ = await _setup(
        db_session, salon_phone="+70000000205", master_phone="+79993330205")
    async with db_session() as db:
        salon = (await db.execute(select(Salon).where(Salon.id == salon_id))).scalar_one()
        salon.published_at = None
        await db.commit()
    r = await client.get(f"/book/{salon_id}")
    assert r.status_code == 200 and "Запись недоступна" in r.text


async def test_refusal_when_salon_is_not_approved(client, db_session):
    salon_id, _, _ = await _setup(
        db_session, salon_phone="+70000000206", master_phone="+79993330206")
    async with db_session() as db:
        salon = (await db.execute(select(Salon).where(Salon.id == salon_id))).scalar_one()
        salon.moderation_status = SalonModerationStatus.PENDING
        await db.commit()
    r = await client.get(f"/book/{salon_id}")
    assert r.status_code == 200 and "Запись недоступна" in r.text


async def test_taken_slot_is_refused(client, db_session):
    """Два человека жмут «Записаться» на одно окно: второму должно прийти
    «занято», а не вторая бронь."""
    salon_id, master_id, svc_id = await _setup(
        db_session, salon_phone="+70000000207", master_phone="+79993330207")
    payload = _payload(salon_id, master_id, svc_id, "+79991110001")

    first = await client.post("/api/v1/guest/booking", json=payload)
    assert first.status_code == 200, first.text

    second = await client.post(
        "/api/v1/guest/booking",
        json={**payload, "phone": "+79991110002"})
    assert second.status_code >= 400, second.text

    async with db_session() as db:
        start = datetime.fromisoformat(payload["start_time"])
        rows = (await db.execute(
            select(Booking).where(
                Booking.master_id == master_id,
                Booking.status != BookingStatus.CANCELLED,
            )
        )).scalars().all()
        at_that_time = [b for b in rows
                        if b.start_time.replace(tzinfo=None) == start.replace(tzinfo=None)]
        assert len(at_that_time) == 1


async def test_booking_in_the_past_is_refused(client, db_session):
    salon_id, master_id, svc_id = await _setup(
        db_session, salon_phone="+70000000208", master_phone="+79993330208")
    past = (datetime.now() - timedelta(days=1)).replace(hour=12, minute=0,
                                                        second=0, microsecond=0)
    r = await client.post(
        "/api/v1/guest/booking",
        json=_payload(salon_id, master_id, svc_id, "+79991110003",
                      start_time=past.isoformat()))
    assert r.status_code >= 400


async def test_manage_page_shows_status_as_a_toned_chip(client, db_session):
    """Статус брони раньше красился инлайновым цветом по словарю (#27ae60 и
    подобные), не совпадавшим ни с токенами, ни между собой, и в тёмной теме
    не читался. Теперь это плашка слоя: слово плюс тон."""
    salon_id, master_id, svc_id = await _setup(
        db_session, salon_phone="+70000000209", master_phone="+79993330209")
    r = await client.post("/api/v1/guest/booking",
                          json=_payload(salon_id, master_id, svc_id, "+79991110004"))
    token = r.json()["manage_token"]

    page = await client.get(f"/guest-booking/{token}")
    assert page.status_code == 200
    assert "Ваша запись" in page.text
    assert "r-status r-status--warning" in page.text
    assert "Ожидает подтверждения салона" in page.text
    # Цвет не единственный носитель смысла — рядом всегда слово.
    assert not re.search(r'style="[^"]*color:\s*#', page.text)
    assert 'id="gb-cancel"' in page.text


async def test_manage_page_hides_cancel_for_a_cancelled_booking(client, db_session):
    salon_id, master_id, svc_id = await _setup(
        db_session, salon_phone="+70000000210", master_phone="+79993330210")
    r = await client.post("/api/v1/guest/booking",
                          json=_payload(salon_id, master_id, svc_id, "+79991110005"))
    token = r.json()["manage_token"]
    await client.post(f"/api/v1/guest/booking/{token}/cancel")

    page = await client.get(f"/guest-booking/{token}")
    assert "Отменена" in page.text
    assert 'id="gb-cancel"' not in page.text


async def test_manage_page_refuses_an_unknown_token(client):
    r = await client.get("/guest-booking/нет-такого-токена")
    assert r.status_code == 200 and "Бронь не найдена" in r.text
