# tests/test_cabinet_client.py
"""Кабинет клиента: мои записи, избранное, профиль.

Заход «кабинет клиента» (решение 0011, п. 14). Проверяем не «страница
открылась», а то, что переделка вида ничего не потеряла:

  * каждая форма профиля на месте, сохраняется и читается из базы;
  * согласие уходит в журнал вместе с редакцией документа;
  * удаление аккаунта достижимо и работает;
  * подключение и переключение каналов уведомлений не сломано;
  * отмена записи снимает именно её и только у своего владельца;
  * отзыв предлагается ровно тогда, когда его разрешает ReviewService;
  * пустые состояния ведут в каталог ССЫЛКОЙ, а не текстом;
  * второго набора кнопок и карточек в кабинете нет.
"""
import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.security import get_password_hash, verify_password
from app.models.models import (
    Booking, BookingStatus, ConsentDocument, Favorite, Master, Review,
    ReviewTargetType, Salon, SalonModerationStatus, Service, User, UserConsent,
    UserRole,
)
from app.services.price import format_service_price
from app.web.pages.legal import LEGAL_VERSION
from tests.conftest import register_user

_WORK = json.dumps({d: "08:00-22:00" for d in
                    ("mon", "tue", "wed", "thu", "fri", "sat", "sun")})


async def _login(client, phone, password="Testpass1"):
    r = await client.post("/api/v1/auth/login-web",
                          data={"phone": phone, "password": password})
    assert r.status_code == 302, r.text


async def _user(db_session, phone) -> User:
    async with db_session() as db:
        return (await db.execute(select(User).where(User.phone == phone))).scalar_one()


async def _salon(db_session, *, name, phone, master_phone, master_name="Мастер Тестов",
                 published=True, active=True, hidden=False, tier_days=30):
    """Салон с одним активным мастером и услугой. Видимый в каталоге по
    умолчанию; параметрами можно сделать его невидимым."""
    async with db_session() as db:
        master_user = User(phone=master_phone, full_name=master_name,
                           hashed_password=get_password_hash("Testpass1"),
                           role=UserRole.MASTER)
        db.add(master_user)
        await db.commit()
        await db.refresh(master_user)

        salon = Salon(
            name=name, address="ул. Тестовая, 7", phone=phone, city="Томск",
            latitude=56.5, longitude=84.9, timezone="Asia/Tomsk",
            moderation_status=SalonModerationStatus.APPROVED,
            is_active=active, is_hidden=hidden, working_hours=_WORK,
            published_at=datetime.now() if published else None,
            access_until=datetime.now() + timedelta(days=tier_days),
            creator_id=master_user.id,
        )
        db.add(salon)
        await db.commit()
        await db.refresh(salon)

        master = Master(user_id=master_user.id, salon_id=salon.id,
                        specialization="Маникюр", is_active=True)
        db.add(master)
        await db.commit()
        await db.refresh(master)

        service = Service(master_id=master.id, name="Маникюр", price=1200,
                          duration_minutes=60, is_active=True)
        db.add(service)
        await db.commit()
        await db.refresh(service)
        return {"salon_id": salon.id, "master_id": master.id,
                "service_id": service.id}


async def _book(db_session, *, client_id, stand, when, status, price=1200):
    async with db_session() as db:
        booking = Booking(client_id=client_id, master_id=stand["master_id"],
                          service_id=stand["service_id"], start_time=when,
                          end_time=when + timedelta(minutes=60),
                          status=status, final_price=price)
        db.add(booking)
        await db.commit()
        await db.refresh(booking)
        return booking.id


# =====================================================================
# ПРОФИЛЬ: формы
# =====================================================================

async def test_profile_shows_every_form_action(client, db_session, monkeypatch):
    """Ни один эндпоинт профиля не исчез из разметки.

    Это главная защита переделки вида: восемь форм раскладывались заново, и
    любая потерянная означала бы настройку, до которой человеку больше не
    добраться.
    """
    from app.core.config import settings
    # Блок смены телефона существует только там, где есть чем подтвердить
    # владение номером, — так было и до переделки. Включаем, чтобы проверить
    # саму форму, а не ветку «временно недоступно».
    monkeypatch.setattr(settings, "TG_VERIFY_ENABLED", True)

    phone = "+79995550101"
    await register_user(client, phone)
    await _login(client, phone)

    r = await client.get("/profile")
    assert r.status_code == 200
    for action in (
        "/api/v1/users/me/update-form",        # имя и «о себе»
        "/api/v1/users/me/phone-form",         # смена телефона
        "/api/v1/users/me/city-form",          # смена города
        "/api/v1/users/me/email-form",         # смена почты
        "/api/v1/users/me/password-form",      # смена пароля
        "/api/v1/users/me/delete-form",        # удаление аккаунта
    ):
        assert f'action="{action}"' in r.text, f"потерялась форма {action}"

    # Отвязка мессенджера — седьмая форма, видна только у подключённого
    # канала; её проверяет test_disconnect_form_appears_for_a_connected_channel.
    # Аватар — не форма, а JS-загрузка: проверяем её поле и кнопку.
    assert 'id="profile-avatar-input"' in r.text
    assert 'id="profile-avatar-edit"' in r.text
    # Кнопка подтверждения номера и её эндпоинт.
    assert "/api/v1/auth/register/tg-start" in r.text
    # Тема — локальный выбор, переключатели на месте.
    assert 'data-theme="light"' in r.text and 'data-theme="dark"' in r.text


async def test_profile_says_so_when_phone_change_is_unavailable(client, db_session):
    """Без включённой верификации смена телефона недоступна, и страница
    говорит это прямо, а не показывает форму, которая не сработает."""
    phone = "+79995550121"
    await register_user(client, phone)
    await _login(client, phone)
    r = await client.get("/profile")
    assert "Смена телефона временно недоступна" in r.text
    assert 'action="/api/v1/users/me/phone-form"' not in r.text


async def test_disconnect_form_appears_for_a_connected_channel(client, db_session):
    """Отвязать мессенджер можно: форма появляется у подключённого канала."""
    phone = "+79995550122"
    await register_user(client, phone)
    await _login(client, phone)
    user = await _user(db_session, phone)
    async with db_session() as db:
        obj = await db.get(User, user.id)
        obj.tg_chat_id = 123456
        await db.commit()

    r = await client.get("/profile")
    assert 'action="/api/v1/users/me/disconnect-channel"' in r.text
    assert 'value="tg"' in r.text
    assert "подключён" in r.text


async def test_profile_name_form_saves_and_reads_back(client, db_session):
    phone = "+79995550102"
    await register_user(client, phone)
    await _login(client, phone)

    r = await client.post("/api/v1/users/me/update-form",
                          data={"full_name": "Новое Имя"})
    assert r.status_code == 302 and "success=updated" in r.headers["location"]
    assert (await _user(db_session, phone)).full_name == "Новое Имя"

    # И оно видно на странице — иначе сохранение нечем подтвердить глазами.
    page = await client.get("/profile")
    assert "Новое Имя" in page.text


async def test_profile_city_form_saves_and_reads_back(client, db_session):
    phone = "+79995550103"
    await register_user(client, phone)
    await _login(client, phone)

    r = await client.post("/api/v1/users/me/city-form", data={"city": "Томск"})
    assert r.status_code == 302 and "success=city_updated" in r.headers["location"]
    assert (await _user(db_session, phone)).city == "Томск"

    page = await client.get("/profile")
    assert "<dt>Город</dt><dd>Томск</dd>" in page.text


async def test_profile_password_form_saves_and_reads_back(client, db_session):
    phone = "+79995550104"
    await register_user(client, phone)
    await _login(client, phone)

    r = await client.post("/api/v1/users/me/password-form", data={
        "current_password": "Testpass1",
        "new_password": "Newpass123",
        "confirm_password": "Newpass123",
    })
    assert r.status_code == 302 and "success=password_updated" in r.headers["location"]
    user = await _user(db_session, phone)
    assert verify_password("Newpass123", user.hashed_password)


async def test_profile_phone_form_saves_and_reads_back(client, db_session, monkeypatch):
    """Телефон меняется только с подтверждением владения новым номером."""
    phone = "+79995550105"
    await register_user(client, phone)
    await _login(client, phone)

    # Подтверждение владения номером эмулируем: сам TG/MAX-флоу покрыт
    # отдельно (test_otp_telegram, test_otp_max).
    async def _ok(request_id, code, ph):
        return True

    monkeypatch.setattr("app.services.otp.verify_code", _ok)
    r = await client.post("/api/v1/users/me/phone-form",
                          data={"phone": "+79995550199", "request_id": "x"})
    assert r.status_code == 302 and "success=phone_updated" in r.headers["location"]
    assert (await _user(db_session, "+79995550199")).phone == "+79995550199"


@pytest.fixture()
def fake_arq(monkeypatch):
    """send_email_code ставит письмо в очередь — подменяем пул, ловим джобы."""
    jobs = []

    class FakePool:
        async def enqueue_job(self, fn, *args, **kwargs):
            jobs.append((fn, args))

    async def _pool():
        return FakePool()

    monkeypatch.setattr("app.services.email_verify.get_arq_pool", _pool)
    return jobs


async def test_profile_email_form_saves_and_reads_back(client, db_session, fake_arq):
    """Почта меняется с кодом, отправленным на НОВЫЙ адрес."""
    phone = "+79995550106"
    await register_user(client, phone)
    await _login(client, phone)

    r = await client.post("/api/v1/users/me/email/send-code",
                          data={"email": "new@rrumi.ru"})
    assert r.status_code == 200, r.text
    sent = r.json()

    r = await client.post("/api/v1/users/me/email-form", data={
        "email": "new@rrumi.ru", "request_id": sent["request_id"],
        "code": sent["dev_code"],
    })
    assert r.status_code == 302 and "success=email_updated" in r.headers["location"]
    assert (await _user(db_session, phone)).email == "new@rrumi.ru"

    page = await client.get("/profile")
    assert "<dt>Почта</dt><dd>new@rrumi.ru</dd>" in page.text


async def test_profile_reports_result_of_every_form(client, db_session):
    """Сообщение из адреса доезжает до экрана.

    До этого захода /profile не читал ни success, ни error, хотя все формы
    отвечают редиректом именно с ними: человек менял пароль и не видел ни
    «готово», ни «неверный текущий пароль».
    """
    phone = "+79995550107"
    await register_user(client, phone)
    await _login(client, phone)

    ok = await client.get("/profile?success=password_updated")
    assert "Пароль изменён" in ok.text
    assert 'class="r-notice r-notice--success"' in ok.text

    bad = await client.get("/profile?error=wrong_password")
    assert "Неверный текущий пароль" in bad.text
    assert 'role="alert"' in bad.text


# =====================================================================
# ПРОФИЛЬ: согласия, каналы, удаление
# =====================================================================

async def test_registration_consent_lands_in_journal_with_version(client, db_session):
    """Согласие пишется в журнал с редакцией документа.

    Профиль показывает человеку, что он согласился и какая редакция
    действует; доказательством остаётся журнал, и его запись обязана нести
    версию (п. 8 Согласия, ч. 2 ст. 9 152-ФЗ).
    """
    phone = "+79995550111"
    code = await client.post("/api/v1/auth/register/send-code", json={"phone": phone})
    assert code.status_code == 200, code.text
    otp = code.json()

    r = await client.post("/api/v1/auth/register-web", data={
        "phone": phone, "full_name": "Тест", "password": "Testpass1",
        "request_id": otp["request_id"], "code": otp["dev_code"],
        "pd_consent": "1", "consent_version": LEGAL_VERSION,
    })
    assert r.status_code == 302, r.text
    assert "error" not in r.headers["location"], r.headers["location"]

    async with db_session() as db:
        rows = (await db.execute(select(UserConsent).where(
            UserConsent.phone == phone,
            UserConsent.document == ConsentDocument.PD_CONSENT,
        ))).scalars().all()
    assert rows, "согласие не попало в журнал"
    assert rows[0].version == LEGAL_VERSION


async def test_profile_links_the_documents_and_names_the_edition(client, db_session):
    """Раздел «Согласия и документы» называет редакцию и ведёт в документы.

    До этого захода в профиле не было НИ слова ни о согласиях, ни о
    документах: единственная ссылка на /legal стояла в подвале.
    """
    phone = "+79995550112"
    await register_user(client, phone)
    await _login(client, phone)

    r = await client.get("/profile")
    assert "Согласия и документы" in r.text
    assert 'href="/consent"' in r.text
    assert 'href="/privacy"' in r.text
    assert 'href="/terms"' in r.text
    assert 'href="/legal"' in r.text
    from app.web.pages.legal import LEGAL_VERSION_HUMAN
    assert LEGAL_VERSION_HUMAN in r.text


async def test_promo_consent_state_is_shown_not_invented(client, db_session):
    """Состояние рекламной рассылки читается из настроек, а не выдумывается.

    Включить её может ТОЛЬКО ad_consent.grant (он пишет доказательство в
    журнал), поэтому профиль показывает факт и говорит, где рычаг.
    """
    phone = "+79995550113"
    await register_user(client, phone)
    await _login(client, phone)

    off = await client.get("/profile")
    assert "Рассылка об акциях и конкурсах" in off.text
    assert "выключена" in off.text

    user = await _user(db_session, phone)
    from app.services import ad_consent
    async with db_session() as db:
        assert await ad_consent.grant(db, user_id=user.id, source="test") is True

    on = await client.get("/profile")
    assert "включена" in on.text

    # Согласие на рекламу тоже легло в журнал со своей версией.
    async with db_session() as db:
        rows = (await db.execute(select(UserConsent).where(
            UserConsent.user_id == user.id,
            UserConsent.document == ConsentDocument.ADS_PROMOS,
        ))).scalars().all()
    assert rows and rows[0].version == ad_consent.VERSION


async def test_delete_account_is_reachable_and_works(client, db_session):
    """Право уйти обязано быть достижимо: форма видна без раскрытия чего-либо
    (152-ФЗ, ч. 2 ст. 9 — согласие отзывается в любой момент)."""
    phone = "+79995550114"
    await register_user(client, phone)
    await _login(client, phone)

    page = await client.get("/profile")
    # Не внутри <details>: раздел стоит на экране целиком.
    body = page.text
    assert 'id="delete-account-form"' in body
    assert "Удаление аккаунта" in body
    head, _, tail = body.partition('id="delete-account-form"')
    assert head.count("<details") == head.count("</details>"), \
        "форма удаления оказалась внутри свёрнутого блока"

    r = await client.post("/api/v1/users/me/delete-form",
                          data={"password": "Testpass1"})
    assert r.status_code == 302
    assert (await _user(db_session, phone)).is_active is False


async def test_notify_channel_switch_still_works(client, db_session):
    """Переключение канала уведомлений не сломано переделкой вида."""
    phone = "+79995550115"
    await register_user(client, phone)
    await _login(client, phone)

    # Без подключённых каналов страница зовёт подключить, а не молчит.
    empty = await client.get("/profile")
    assert "Канал уведомлений не подключён" in empty.text

    # Появилась почта — канал стал доступен, и его можно выбрать.
    user = await _user(db_session, phone)
    async with db_session() as db:
        obj = await db.get(User, user.id)
        obj.email = "ch@example.com"
        await db.commit()

    page = await client.get("/profile")
    assert 'id="notify-method"' in page.text
    assert 'action="/api/v1/users/me/notify-channel"' in page.text

    r = await client.post("/api/v1/users/me/notify-channel", data={"channel": "email"})
    assert r.status_code == 302 and "success=notify_channel_updated" in r.headers["location"]

    async with db_session() as db:
        obj = await db.get(User, user.id)
        assert obj.notify_channel.value == "email"


async def test_channel_state_is_a_word_not_only_a_colour(client, db_session):
    """Состояние канала названо словом: смысл не передаётся одним цветом."""
    phone = "+79995550116"
    await register_user(client, phone)
    await _login(client, phone)
    user = await _user(db_session, phone)
    async with db_session() as db:
        obj = await db.get(User, user.id)
        obj.email = "w@example.com"
        # Один канал ПОДКЛЮЧЁН, другой нет — на странице обязаны быть оба
        # состояния словом, иначе тест смотрит на ветку, которой нет.
        obj.tg_chat_id = 777001
        await db.commit()

    r = await client.get("/profile")
    assert "не подключён" in r.text        # MAX
    assert ">подключён<" in r.text         # Telegram
    assert "подтверждён" in r.text         # телефон
    # Каждое состояние — общая плашка ui.status, а не крашеный <span>.
    assert 'class="r-status r-status--success">подключён<' in r.text
    # Прежняя версия красила значение инлайновым цветом — его больше нет.
    assert "color:#22c55e" not in r.text
    assert "color:#ef4444" not in r.text
    assert "color:var(--color-muted)" not in r.text


# =====================================================================
# ЗАПИСИ: отмена и отзыв
# =====================================================================

async def test_cancel_cancels_exactly_this_booking(client, db_session):
    """Отмена снимает ИМЕННО эту запись и не трогает соседнюю."""
    phone = "+79995550201"
    data = await register_user(client, phone)
    await _login(client, phone)
    client_id = data["user"]["id"]
    stand = await _salon(db_session, name="Салон Отмен", phone="+70000000601",
                         master_phone="+79995550202")

    first = await _book(db_session, client_id=client_id, stand=stand,
                        when=datetime.now() + timedelta(days=1),
                        status=BookingStatus.CONFIRMED)
    second = await _book(db_session, client_id=client_id, stand=stand,
                         when=datetime.now() + timedelta(days=3),
                         status=BookingStatus.CONFIRMED)

    r = await client.post(f"/api/v1/bookings/{first}/cancel")
    assert r.status_code == 200, r.text

    async with db_session() as db:
        assert (await db.get(Booking, first)).status == BookingStatus.CANCELLED
        assert (await db.get(Booking, second)).status == BookingStatus.CONFIRMED


async def test_cancel_only_by_owner(client, db_session):
    """Чужую запись отменить нельзя — 404, и статус не меняется."""
    owner = "+79995550203"
    stranger = "+79995550204"
    data = await register_user(client, owner)
    await register_user(client, stranger)
    stand = await _salon(db_session, name="Салон Чужой", phone="+70000000602",
                         master_phone="+79995550205")
    booking = await _book(db_session, client_id=data["user"]["id"], stand=stand,
                          when=datetime.now() + timedelta(days=1),
                          status=BookingStatus.CONFIRMED)

    await _login(client, stranger)
    r = await client.post(f"/api/v1/bookings/{booking}/cancel")
    assert r.status_code == 404

    async with db_session() as db:
        assert (await db.get(Booking, booking)).status == BookingStatus.CONFIRMED


async def test_cancel_offered_only_for_upcoming(client, db_session):
    """Кнопка отмены стоит у предстоящей и не стоит у прошедшей: сервер
    отказывает отменять завершённую, и предлагать это нельзя."""
    phone = "+79995550206"
    data = await register_user(client, phone)
    await _login(client, phone)
    stand = await _salon(db_session, name="Салон Кнопок", phone="+70000000603",
                         master_phone="+79995550207")

    done = await _book(db_session, client_id=data["user"]["id"], stand=stand,
                       when=datetime.now() - timedelta(days=2),
                       status=BookingStatus.COMPLETED)
    page = await client.get("/bookings")
    assert f'data-booking-id="{done}"' in page.text
    assert "booking-cancel-btn" not in page.text

    soon = await _book(db_session, client_id=data["user"]["id"], stand=stand,
                       when=datetime.now() + timedelta(days=1),
                       status=BookingStatus.CONFIRMED)
    page = await client.get("/bookings")
    assert "booking-cancel-btn" in page.text
    assert f'data-booking-id="{soon}"' in page.text


async def test_cancel_confirms_in_a_sheet_not_in_confirm(client, db_session):
    """Подтверждение отмены — лист снизу (ui.sheet), а не confirm() браузера."""
    phone = "+79995550208"
    data = await register_user(client, phone)
    await _login(client, phone)
    stand = await _salon(db_session, name="Салон Листа", phone="+70000000604",
                         master_phone="+79995550209")
    await _book(db_session, client_id=data["user"]["id"], stand=stand,
                when=datetime.now() + timedelta(days=1),
                status=BookingStatus.CONFIRMED)

    r = await client.get("/bookings")
    assert 'id="cancelSheet"' in r.text
    assert 'class="r-sheet"' in r.text
    assert 'role="dialog"' in r.text and 'aria-modal="true"' in r.text


async def test_review_offered_exactly_when_the_server_allows_it(client, db_session):
    """Отзыв предлагается ровно тогда, когда его разрешает ReviewService.

    Правило сервера: завершённая запись И отзыва на ЭТУ ЦЕЛЬ (мастера) ещё
    нет. Прежняя страница искала отзыв по booking_id и потому предлагала
    кнопку тому, кто уже оценил этого мастера другой записью, — сервер
    отвечал 409 «Вы уже оставляли отзыв на эту цель».
    """
    phone = "+79995550210"
    data = await register_user(client, phone)
    await _login(client, phone)
    client_id = data["user"]["id"]
    stand = await _salon(db_session, name="Салон Отзывов", phone="+70000000605",
                         master_phone="+79995550211")

    # 1. Предстоящая — отзыва нет и быть не может.
    await _book(db_session, client_id=client_id, stand=stand,
                when=datetime.now() + timedelta(days=1),
                status=BookingStatus.CONFIRMED)
    page = await client.get("/bookings")
    assert "booking-review-add-btn" not in page.text

    # 2. Завершённая — кнопка появилась.
    first = await _book(db_session, client_id=client_id, stand=stand,
                        when=datetime.now() - timedelta(days=5),
                        status=BookingStatus.COMPLETED)
    page = await client.get("/bookings")
    assert "booking-review-add-btn" in page.text

    # 3. Вторая завершённая у ТОГО ЖЕ мастера плюс оставленный отзыв: кнопки
    #    «оставить» больше нет НИ У ОДНОЙ из двух — сервер второй не примет.
    second = await _book(db_session, client_id=client_id, stand=stand,
                         when=datetime.now() - timedelta(days=2),
                         status=BookingStatus.COMPLETED)
    async with db_session() as db:
        db.add(Review(client_id=client_id, salon_id=stand["salon_id"],
                      target_type=ReviewTargetType.MASTER,
                      master_id=stand["master_id"], rating=5, comment="Хорошо",
                      is_verified=True, booking_id=first))
        await db.commit()

    page = await client.get("/bookings")
    assert "booking-review-add-btn" not in page.text
    # Зато оставленный отзыв виден у обеих — он про мастера, а не про запись.
    assert page.text.count("booking-review-edit-btn") == 2
    assert "Хорошо" in page.text

    # 4. И сервер действительно отказал бы: проверяем, что предложение
    #    совпадало с правилом, а не угадывало.
    r = await client.post("/api/v1/reviews/create", data={
        "salon_id": stand["salon_id"], "target_type": "master",
        "master_id": stand["master_id"], "rating": "4", "comment": "ещё",
        "booking_id": str(second),
    })
    assert r.status_code == 409


# =====================================================================
# ИЗБРАННОЕ
# =====================================================================

async def test_favorites_show_the_same_card_as_the_catalog(client, db_session):
    """Карточка салона в избранном — ТА ЖЕ, что в каталоге: тот же класс, те
    же услуги с ценой. Прежняя версия рисовала свою, беднее."""
    phone = "+79995550301"
    data = await register_user(client, phone)
    await _login(client, phone)
    stand = await _salon(db_session, name="Салон Избранный", phone="+70000000701",
                         master_phone="+79995550302")

    async with db_session() as db:
        db.add(Favorite(user_id=data["user"]["id"], salon_id=stand["salon_id"]))
        await db.commit()

    catalog = await client.get("/salons")
    fav = await client.get("/favorites")

    for page in (catalog, fav):
        assert f'<article class="r-salon salon-card" data-salon-id="{stand["salon_id"]}">' in page.text
        assert 'class="r-svc__name">Маникюр<' in page.text
        assert format_service_price(1200, None) in page.text
        assert "60 мин" in page.text

    # Своей карточки у избранного больше нет.
    assert "fav-card" not in fav.text


async def test_favorites_heart_is_the_only_remove_control(client, db_session):
    """Убирают тем же сердечком, которым добавляли: второго органа управления
    одним и тем же в кабинете нет."""
    phone = "+79995550303"
    data = await register_user(client, phone)
    await _login(client, phone)
    stand = await _salon(db_session, name="Салон Сердечка", phone="+70000000702",
                         master_phone="+79995550304")
    async with db_session() as db:
        db.add(Favorite(user_id=data["user"]["id"], salon_id=stand["salon_id"]))
        await db.commit()

    r = await client.get("/favorites")
    # Сердечко приходит закрашенным с сервера и названо тем, что делает.
    assert 'aria-label="Убрать из избранного"' in r.text
    assert 'aria-pressed="true"' in r.text
    assert "fav-remove-btn" not in r.text
    # На карточке ровно один орган управления избранным и ровно одна ссылка
    # «внутрь» — отдельной кнопки «Убрать» рядом с сердечком нет.
    card = r.text.split('<article class="r-salon')[1].split("</article>")[0]
    assert card.count("favorite-btn") == 1
    assert card.count("r-salon__all") == 1
    # Слово «Убрать» в карточке встречается только как подпись сердечка
    # (aria-label и title), отдельной кнопкой — нет.
    assert card.count("Убрать") == 2
    assert "r-btn" not in card.split("r-salon__all")[0]
    # Подтверждение — лист снизу, как у отмены записи.
    assert 'id="favSheet"' in r.text


async def test_favorites_keep_a_salon_whose_tariff_expired(client, db_session):
    """Салон без оплаченного тарифа из личного списка не исчезает: человек
    решил бы, что сам его удалил. Условие то же, что до переделки вида."""
    phone = "+79995550305"
    data = await register_user(client, phone)
    await _login(client, phone)
    stand = await _salon(db_session, name="Салон Без Тарифа", phone="+70000000703",
                         master_phone="+79995550306", tier_days=-1)
    async with db_session() as db:
        db.add(Favorite(user_id=data["user"]["id"], salon_id=stand["salon_id"]))
        await db.commit()

    # В каталоге его нет...
    catalog = await client.get("/salons")
    assert "Салон Без Тарифа" not in catalog.text
    # ...а в избранном есть.
    fav = await client.get("/favorites")
    assert "Салон Без Тарифа" in fav.text


async def test_favorites_drop_a_salon_hidden_by_its_owner(client, db_session):
    """Скрытый владельцем салон в избранном не показывается — так было и до
    переделки."""
    phone = "+79995550307"
    data = await register_user(client, phone)
    await _login(client, phone)
    stand = await _salon(db_session, name="Салон Скрытый", phone="+70000000704",
                         master_phone="+79995550308", hidden=True)
    async with db_session() as db:
        db.add(Favorite(user_id=data["user"]["id"], salon_id=stand["salon_id"]))
        await db.commit()

    r = await client.get("/favorites")
    assert "Салон Скрытый" not in r.text


# =====================================================================
# ПУСТЫЕ СОСТОЯНИЯ И ЕДИНСТВО МИРА
# =====================================================================

@pytest.mark.parametrize("url", ["/bookings", "/favorites"])
async def test_empty_states_lead_to_the_catalog_by_a_link(client, db_session, url):
    """Пустое состояние ведёт в каталог ССЫЛКОЙ, а не сообщает о пустоте."""
    phone = "+7999555040" + ("1" if url == "/bookings" else "2")
    await register_user(client, phone)
    await _login(client, phone)

    r = await client.get(url)
    assert r.status_code == 200
    assert 'class="r-empty"' in r.text
    # Ссылка на каталог, а не текст «добавьте что-нибудь».
    assert 'href="/salons"' in r.text
    assert "Открыть каталог" in r.text


@pytest.mark.parametrize("url", ["/bookings", "/favorites", "/profile"])
async def test_cabinet_has_no_second_set_of_buttons_and_cards(client, db_session, url):
    """Кабинет не рисует своих кнопок и карточек: всё приходит из ui.py.

    Проверяем отсутствие старых, доставшихся от прежних версий классов —
    именно они и были вторым набором. Тест намеренно смотрит на разметку:
    стоит вернуть на страницу .btn-primary или .booking-card с собственной
    рамкой, и экран разойдётся с витриной.
    """
    phone = "+7999555041" + {"/bookings": "1", "/favorites": "2", "/profile": "3"}[url]
    await register_user(client, phone)
    await _login(client, phone)

    r = await client.get(url)
    assert r.status_code == 200
    for stale in ('class="btn-primary"', 'class="btn-outline"', "btn-mini",
                  "empty-state\"", "settings-card", "fav-card",
                  "review-modal", "booking-info-grid", "tab-btn"):
        assert stale not in r.text, f"{url}: вернулся второй набор — {stale}"

    # Кнопки — общие.
    assert "r-btn" in r.text


@pytest.mark.parametrize("url", ["/bookings", "/favorites", "/profile"])
async def test_cabinet_pages_are_not_indexed(client, db_session, url):
    """Личные страницы не отдаются поисковикам."""
    phone = "+7999555042" + {"/bookings": "1", "/favorites": "2", "/profile": "3"}[url]
    await register_user(client, phone)
    await _login(client, phone)
    r = await client.get(url)
    assert 'name="robots" content="noindex, nofollow"' in r.text


@pytest.mark.parametrize("url", ["/bookings", "/favorites", "/profile"])
async def test_cabinet_pages_cover_the_notch(client, db_session, url):
    """viewport-fit=cover — иначе safe-area у закреплённых элементов не
    работает вовсе, и лист снизу уезжает под полосу жеста «домой»."""
    phone = "+7999555043" + {"/bookings": "1", "/favorites": "2", "/profile": "3"}[url]
    await register_user(client, phone)
    await _login(client, phone)
    r = await client.get(url)
    assert "viewport-fit=cover" in r.text


@pytest.mark.parametrize("url", ["/bookings", "/favorites"])
async def test_card_lists_do_not_stretch_past_the_screen(client, db_session, url):
    """Списки карточек заданы через minmax(0, 1fr).

    Иначе элемент сетки не уже своего min-content: длинная плашка состояния
    (у неё white-space: nowrap) распирала колонку, карточка вылезала за
    контейнер, и на 375px появлялась горизонтальная прокрутка ВСЕЙ страницы.
    Воспроизведено в браузере 04.10.2026 — поэтому проверяем сам приём, а не
    только то, что страница открылась.
    """
    from pathlib import Path

    css = Path("static/src/css/bookings.css" if url == "/bookings"
               else "static/src/css/favorites.css").read_text(encoding="utf-8")
    selector = ".bookings-list" if url == "/bookings" else ".fav-list"
    block = css.split(selector + " {", 1)[1].split("}", 1)[0]
    assert "minmax(0, 1fr)" in block, f"{selector}: колонка без minmax(0, …)"


def test_profile_survives_config_reload(monkeypatch):
    """Профиль читает настройки ПОСЛЕ перезагрузки конфига, а не до неё.

    ``app.core.config`` перезагружается (guard'ы конфига и их тесты зовут
    ``importlib.reload``), и после этого в модуле лежит НОВЫЙ объект настроек.
    Страница, сделавшая ``from app.core.config import settings`` на уровне
    модуля, навсегда остаётся со старым — и кнопка «Переподключить» в плашке
    «мессенджер не принимает сообщения» молча теряет адрес бота.

    Ровно это и случилось при переделке вида: тест ловил поломку только в
    полном прогоне, где перезагрузка успевала произойти раньше.
    """
    import importlib
    from datetime import datetime, timezone

    import app.core.config as config_mod
    from app.models.models import NotifyChannel
    from app.web.pages.profile import _notify_channel_block

    # Эмулируем то, что делает test_config_guards: новый объект настроек.
    importlib.reload(config_mod)
    monkeypatch.setattr(config_mod.settings, "TG_BOT_USERNAME", "rumi_reload_bot")

    user = User(phone="+79990000000", tg_chat_id=1, email="a@b.ru",
                notify_channel=NotifyChannel.TG,
                tg_broken_at=datetime.now(timezone.utc))
    html = _notify_channel_block(user)
    assert "https://t.me/rumi_reload_bot" in html, \
        "страница держит настройки, прочитанные до перезагрузки конфига"
