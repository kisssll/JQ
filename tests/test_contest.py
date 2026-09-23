# tests/test_contest.py
"""Конкурс: анкета в боте, заявки и страница правил.

Главное, что закрепляем: заявка попадает в нашу базу вместе с записью
согласия (а не в гугл-форму за границей), правила объявлены на сайте, как
требует ст. 9 закона «О рекламе», и бот не обещает того, чего организатор
не назвал.
"""
from datetime import date

import pytest
from sqlalchemy import select

from app.models.models import (
    ConsentDocument, ContestEntry, NotifyChannel, User, UserConsent, UserRole,
)
from app.services import contest
from app.core.security import get_password_hash


async def _user(db_session, phone="+79996660100") -> int:
    async with db_session() as db:
        user = User(phone=phone, full_name="Мастер", role=UserRole.CLIENT,
                    hashed_password=get_password_hash("x"))
        db.add(user)
        await db.commit()
        return user.id


@pytest.fixture(autouse=True)
def _entries_open(monkeypatch):
    """Тесты не должны ломаться от календаря: приём заявок открыт."""
    monkeypatch.setattr(contest, "accepts_entries", lambda today=None: True)


async def _fill(db, chat_id, answers=("Алина Агеева", "Томск",
                                      "https://vk.com/wall-1_1", "+79990001122")):
    for value in answers:
        reply, ready = await contest.answer(db, NotifyChannel.VK, chat_id, value)
    return reply, ready


# ── анкета ──────────────────────────────────────────────────────────────────

async def test_entry_goes_to_our_base_with_consent(client, db_session):
    user_id = await _user(db_session)
    async with db_session() as db:
        user = await db.get(User, user_id)
        assert "Вопрос 1 из 4" in await contest.begin(db, NotifyChannel.VK, 601, user)
        reply, ready = await _fill(db, 601)
        assert ready and "Проверьте заявку" in reply and "Томск" in reply
        assert contest.SENT_TEXT == await contest.send(
            db, NotifyChannel.VK, 601, user=user, consent_version="2026-08-18")

    async with db_session() as db:
        entry = (await db.execute(select(ContestEntry))).scalars().one()
        assert (entry.name, entry.city, entry.contact) == ("Алина Агеева", "Томск", "+79990001122")
        assert entry.user_id == user_id and entry.channel == NotifyChannel.VK
        docs = {c.document for c in (await db.execute(
            select(UserConsent).where(UserConsent.user_id == user_id))).scalars()}
        assert ConsentDocument.CONTEST_RULES in docs and ConsentDocument.PD_CONSENT in docs


async def test_entry_works_without_account(client, db_session):
    """Конкурс зовёт мастеров со стороны: требовать аккаунт — терять участников."""
    async with db_session() as db:
        await contest.begin(db, NotifyChannel.VK, 602, None)
        await _fill(db, 602)
        await contest.send(db, NotifyChannel.VK, 602)
    async with db_session() as db:
        entry = (await db.execute(select(ContestEntry))).scalars().one()
        assert entry.user_id is None and entry.chat_id == 602


async def test_bad_link_is_asked_again(client, db_session):
    async with db_session() as db:
        await contest.begin(db, NotifyChannel.VK, 603, None)
        await contest.answer(db, NotifyChannel.VK, 603, "Алина")
        await contest.answer(db, NotifyChannel.VK, 603, "Томск")
        reply, ready = await contest.answer(db, NotifyChannel.VK, 603, "у меня в инсте")
        assert not ready and "ссылка" in reply.lower()
        assert "Вопрос 3 из 4" in reply          # тот же вопрос, а не следующий


async def test_cancel_stops_the_form(client, db_session):
    async with db_session() as db:
        await contest.begin(db, NotifyChannel.VK, 604, None)
        reply, _ = await contest.answer(db, NotifyChannel.VK, 604, "отмена")
        assert "отменена" in reply
        assert await contest.draft_get(NotifyChannel.VK, 604) is None
        # и ответы дальше уже не принимаются
        assert await contest.answer(db, NotifyChannel.VK, 604, "Алина") == ("", False)


async def test_second_entry_from_same_chat_is_refused(client, db_session):
    async with db_session() as db:
        await contest.begin(db, NotifyChannel.VK, 605, None)
        await _fill(db, 605)
        await contest.send(db, NotifyChannel.VK, 605)
        assert "уже принята" in await contest.begin(db, NotifyChannel.VK, 605, None)
    async with db_session() as db:
        assert len((await db.execute(select(ContestEntry))).scalars().all()) == 1


async def test_entries_closed_outside_the_window(client, db_session, monkeypatch):
    monkeypatch.setattr(contest, "accepts_entries", lambda today=None: False)
    async with db_session() as db:
        reply = await contest.begin(db, NotifyChannel.VK, 606, None)
    assert "Приём заявок" in reply
    assert await contest.draft_get(NotifyChannel.VK, 606) is None


async def test_send_without_form_does_not_create_entry(client, db_session):
    async with db_session() as db:
        assert "не заполнена" in await contest.send(db, NotifyChannel.VK, 607)
        assert (await db.execute(select(ContestEntry))).scalars().first() is None


# ── сроки и меню ────────────────────────────────────────────────────────────

def test_menu_button_appears_only_during_contest():
    assert contest.is_menu_visible(date(2026, 10, 5)) is True
    assert contest.is_menu_visible(date(2026, 9, 1)) is False
    assert contest.is_menu_visible(date(2026, 11, 1)) is False


def test_entry_window_closes_before_voting():
    """Голосование начинается 11 октября — принимать заявки после этого
    нельзя, иначе кто-то попадёт в голосование задним числом."""
    assert contest.ENTRY_END < contest.VOTING_START


# ── правила ─────────────────────────────────────────────────────────────────

async def test_rules_page_has_everything_the_law_requires(client):
    r = await client.get("/contest")
    assert r.status_code == 200
    for required in ("Организатор", "ООО «РУМИ»", "Кто может участвовать",
                     "Сроки", "Как определяются победители", "Призы", "18"):
        assert required in r.text, required


async def test_rules_do_not_promise_what_is_unknown(client):
    """Партнёров и площадку финала организатор не назвал — придумывать их
    нельзя: это недостоверная реклама и спор с участником."""
    assert contest.PARTNER_PRIZES is None and contest.FINAL_PLACE is None
    r = await client.get("/contest")
    assert "партнёр" not in r.text.lower()
    assert "место проведения" not in r.text.lower()
    assert "партнёр" not in contest.short_pitch().lower()


def test_pitch_and_rules_tell_the_same_dates():
    pitch = contest.short_pitch(date(2026, 10, 5))
    for day in (contest.ENTRY_START, contest.VOTING_START, contest.FINAL_DATE):
        assert contest.ru_date(day) in pitch
