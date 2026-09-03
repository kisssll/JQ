"""Обращения в поддержку из ботов.

Канал открыт всем, кто нашёл бота, и принимает файлы — поэтому проверяем не
только «дошло», но и заслоны: лимит частоты, минимальную длину, потолок фото.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.models import (
    NotifyChannel, SupportRequest, SupportStatus, SupportTopic, User, UserRole,
)
from app.services.support import (
    MAX_TEXT_LEN, MIN_TEXT_LEN, RATE_LIMIT_PER_HOUR, RateLimited,
    check_rate_limit, create_request, send_answer, validate_text,
)


# ── Приём текста ─────────────────────────────────────────────────────────────

def test_short_text_rejected_with_explanation():
    """«привет» тикетом быть не должен, но отказ обязан объяснять причину."""
    error = validate_text("привет")
    assert error and str(MIN_TEXT_LEN) in error


def test_real_complaint_passes():
    assert validate_text("Не могу войти в кабинет, пишет неверный пароль") is None


def test_overlong_text_rejected():
    assert validate_text("а" * (MAX_TEXT_LEN + 1)) is not None


def test_whitespace_is_not_content():
    assert validate_text("          \n   ") is not None


# ── Лимит частоты ────────────────────────────────────────────────────────────

async def test_rate_limit_trips_after_the_quota():
    chat = 900001
    for _ in range(RATE_LIMIT_PER_HOUR):
        await check_rate_limit(NotifyChannel.TG, chat)
    with pytest.raises(RateLimited):
        await check_rate_limit(NotifyChannel.TG, chat)


async def test_rate_limit_is_per_chat_and_channel():
    """Лимит одного человека не должен глушить остальных."""
    for _ in range(RATE_LIMIT_PER_HOUR):
        await check_rate_limit(NotifyChannel.TG, 900002)
    await check_rate_limit(NotifyChannel.TG, 900003)      # другой чат
    await check_rate_limit(NotifyChannel.MAX, 900002)     # другой канал


# ── Создание обращения ───────────────────────────────────────────────────────

async def test_unlinked_user_can_still_write(db_session, monkeypatch):
    """Самый частый повод написать — «не могу войти», и такой человек как раз
    не привязан. Обращение обязано приниматься без аккаунта."""
    monkeypatch.setattr("app.services.notifications.notify_admins",
                        lambda *a, **kw: _noop())

    async with db_session() as db:
        req = await create_request(
            db, topic=SupportTopic.BUG, text="Не приходит код подтверждения",
            channel=NotifyChannel.TG, chat_id=555001, user=None,
        )
        assert req.user_id is None
        assert req.chat_id == 555001
        assert req.status == SupportStatus.NEW


async def _noop():
    return None


async def test_linked_user_is_attached(db_session, monkeypatch):
    monkeypatch.setattr("app.services.notifications.notify_admins",
                        lambda *a, **kw: _noop())

    async with db_session() as db:
        user = User(phone="+79990009001", full_name="К",
                    hashed_password=get_password_hash("Testpass1"),
                    role=UserRole.CLIENT, is_active=True, tg_chat_id=555002)
        db.add(user)
        await db.commit()
        await db.refresh(user)

        req = await create_request(
            db, topic=SupportTopic.QUESTION, text="Как отменить запись?",
            channel=NotifyChannel.TG, chat_id=555002, user=user,
            photos=["https://example.org/a.jpg"],
        )
        assert req.user_id == user.id
        assert req.photos == ["https://example.org/a.jpg"]


async def test_admins_are_alerted(db_session, monkeypatch):
    """Обращение, о котором никто не узнал, бесполезно."""
    alerts = []

    async def _capture(db, subject, body=""):
        alerts.append(subject)

    monkeypatch.setattr("app.services.notifications.notify_admins", _capture)

    async with db_session() as db:
        await create_request(
            db, topic=SupportTopic.IDEA, text="Добавьте тёмную тему, пожалуйста",
            channel=NotifyChannel.MAX, chat_id=555003,
        )
    assert alerts and "Обращение" in alerts[0]


async def test_alert_failure_does_not_lose_the_request(db_session, monkeypatch):
    """Человек своё уже отправил — падение алерта не должно это отменять."""
    async def _boom(db, subject, body=""):
        raise RuntimeError("канал недоступен")

    monkeypatch.setattr("app.services.notifications.notify_admins", _boom)

    async with db_session() as db:
        req = await create_request(
            db, topic=SupportTopic.BUG, text="Оплата не проходит, ошибка 500",
            channel=NotifyChannel.TG, chat_id=555004,
        )
        assert req.id is not None


# ── Ответ ────────────────────────────────────────────────────────────────────

async def test_answer_to_linked_user_goes_through_his_channel(db_session, monkeypatch):
    sent = []

    async def _deliver(user, text, subject=None):
        sent.append((user.id, text))

    monkeypatch.setattr("app.services.notifications.deliver", _deliver)
    monkeypatch.setattr("app.services.notifications.notify_admins",
                        lambda *a, **kw: _noop())

    async with db_session() as db:
        user = User(phone="+79990009002", full_name="К",
                    hashed_password=get_password_hash("Testpass1"),
                    role=UserRole.CLIENT, is_active=True, tg_chat_id=555005)
        admin = User(phone="+79990009003", full_name="А",
                     hashed_password=get_password_hash("Adminp1"),
                     role=UserRole.ADMIN, is_active=True)
        db.add_all([user, admin])
        await db.commit()
        await db.refresh(user)
        await db.refresh(admin)

        req = await create_request(
            db, topic=SupportTopic.QUESTION, text="Когда спишут деньги?",
            channel=NotifyChannel.TG, chat_id=555005, user=user,
        )
        ok = await send_answer(db, req, "Списание раз в месяц, в день продления.", admin)

    assert ok and sent
    assert "Списание раз в месяц" in sent[0][1]
    async with db_session() as db:
        again = (await db.execute(
            select(SupportRequest).where(SupportRequest.id == req.id)
        )).scalar_one()
        assert again.status == SupportStatus.CLOSED
        assert again.answered_by_id == admin.id
        assert again.answered_at is not None


async def test_answer_to_unlinked_user_goes_into_the_same_chat(db_session, monkeypatch):
    """Аккаунта нет — писать больше некуда, кроме исходного чата."""
    jobs = []

    class _Pool:
        async def enqueue_job(self, name, *args, **kw):
            jobs.append((name, args))

    async def _pool():
        return _Pool()

    monkeypatch.setattr("app.core.worker.get_arq_pool", _pool)
    monkeypatch.setattr("app.services.notifications.notify_admins",
                        lambda *a, **kw: _noop())

    async with db_session() as db:
        admin = User(phone="+79990009004", full_name="А",
                     hashed_password=get_password_hash("Adminp1"),
                     role=UserRole.ADMIN, is_active=True)
        db.add(admin)
        await db.commit()
        await db.refresh(admin)

        req = await create_request(
            db, topic=SupportTopic.BUG, text="Не приходит код в MAX",
            channel=NotifyChannel.MAX, chat_id=555006,
        )
        ok = await send_answer(db, req, "Переустановите бота и повторите.", admin)

    assert ok
    assert jobs and jobs[0][0] == "send_max_message"
    assert jobs[0][1][0] == 555006


# ── Админка ──────────────────────────────────────────────────────────────────

async def test_moderator_can_answer_from_admin_panel(client, db_session, monkeypatch):
    """Разбор обращений — дежурная работа, она доступна обычному модератору,
    а не только старшему."""
    sent = []

    async def _deliver(user, text, subject=None):
        sent.append(text)

    monkeypatch.setattr("app.services.notifications.deliver", _deliver)
    monkeypatch.setattr("app.services.notifications.notify_admins",
                        lambda *a, **kw: _noop())

    async with db_session() as db:
        author = User(phone="+79990009010", full_name="К",
                      hashed_password=get_password_hash("Testpass1"),
                      role=UserRole.CLIENT, is_active=True, tg_chat_id=555010)
        moderator = User(phone="+79990009011", full_name="М",
                         hashed_password=get_password_hash("Modpass1"),
                         role=UserRole.ADMIN, is_senior_admin=False, is_active=True)
        db.add_all([author, moderator])
        await db.commit()
        await db.refresh(author)

        req = await create_request(
            db, topic=SupportTopic.QUESTION, text="Как сменить телефон в профиле?",
            channel=NotifyChannel.TG, chat_id=555010, user=author,
        )
        req_id = req.id

    r = await client.post("/api/v1/auth/login",
                          json={"phone": "+79990009011", "password": "Modpass1"})
    assert r.status_code == 200
    client.cookies.set("access_token", r.json()["access_token"])

    r = await client.post(f"/api/v1/admin/support/{req_id}/answer",
                          data={"answer": "В профиле, раздел «Каналы связи»."},
                          follow_redirects=False)
    assert r.status_code in (302, 303), r.text
    assert sent, "ответ не доставлен автору"

    async with db_session() as db:
        again = (await db.execute(
            select(SupportRequest).where(SupportRequest.id == req_id)
        )).scalar_one()
        assert again.status == SupportStatus.CLOSED
        assert again.answer.startswith("В профиле")


async def test_second_answer_is_refused(client, db_session, monkeypatch):
    """Повторная отправка формы не должна слать человеку второй ответ."""
    sent = []

    async def _deliver(user, text, subject=None):
        sent.append(text)

    monkeypatch.setattr("app.services.notifications.deliver", _deliver)
    monkeypatch.setattr("app.services.notifications.notify_admins",
                        lambda *a, **kw: _noop())

    async with db_session() as db:
        author = User(phone="+79990009012", full_name="К",
                      hashed_password=get_password_hash("Testpass1"),
                      role=UserRole.CLIENT, is_active=True, tg_chat_id=555011)
        moderator = User(phone="+79990009013", full_name="М",
                         hashed_password=get_password_hash("Modpass1"),
                         role=UserRole.ADMIN, is_active=True)
        db.add_all([author, moderator])
        await db.commit()
        await db.refresh(author)
        req = await create_request(
            db, topic=SupportTopic.BUG, text="Кнопка оплаты не нажимается",
            channel=NotifyChannel.TG, chat_id=555011, user=author,
        )
        req_id = req.id

    r = await client.post("/api/v1/auth/login",
                          json={"phone": "+79990009013", "password": "Modpass1"})
    client.cookies.set("access_token", r.json()["access_token"])

    for _ in range(2):
        await client.post(f"/api/v1/admin/support/{req_id}/answer",
                          data={"answer": "Проверьте, обновите страницу."},
                          follow_redirects=False)

    assert len(sent) == 1, "человеку ушло два ответа на одно обращение"


async def test_plain_moderator_sees_the_tab(client, db_session, monkeypatch):
    """Данные вкладки грузились внутри ветки «старший модератор», из-за чего
    у обычного панель падала с UnboundLocalError."""
    monkeypatch.setattr("app.services.notifications.notify_admins",
                        lambda *a, **kw: _noop())

    async with db_session() as db:
        moderator = User(phone="+79990009020", full_name="М",
                         hashed_password=get_password_hash("Modpass1"),
                         role=UserRole.ADMIN, is_senior_admin=False, is_active=True)
        db.add(moderator)
        await db.commit()
        await create_request(
            db, topic=SupportTopic.IDEA, text="Хочу тёмную тему в кабинете",
            channel=NotifyChannel.TG, chat_id=555020,
        )

    r = await client.post("/api/v1/auth/login",
                          json={"phone": "+79990009020", "password": "Modpass1"})
    client.cookies.set("access_token", r.json()["access_token"])

    r = await client.get("/admin")
    assert r.status_code == 200, r.text
    assert 'data-tab="support"' in r.text
    assert "Хочу тёмную тему" in r.text
