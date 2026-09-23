# app/services/contest.py
"""Конкурс мастеров: условия, анкета в боте и приём заявок.

Почему условия лежат в коде одним куском. Конкурс — это стимулирующее
мероприятие: по ст. 9 закона «О рекламе» объявить нужно организатора, сроки,
условия участия, порядок определения победителей и выдачи призов. Всё это
должно совпадать в трёх местах: на странице правил, в рассказе бота и в
рассылке. Разъедутся — спорить придётся с участником, который прочитал одно,
а получил другое.

Заявка принимается в самом боте, а не гугл-формой: гугл-форма — это
персональные данные россиян в базе за границей (152-ФЗ) и прямая неправда в
нашей же политике, где написано, что трансграничной передачи мы не делаем.

Дата окончания приёма заявок (ENTRY_END) выведена из расписания: голосование
начинается 11 октября, значит заявки закрываются накануне. Если у организатора
другие планы — поправить здесь.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

SLUG = "halloween-2026"
TITLE = "Конкурс визажистов «Хеллоуин» от Руми"

ORGANIZER = "ООО «РУМИ» (ОГРН 1267000004370, ИНН 7000036144)"
CONTACT_EMAIL = "hello@rrumi.ru"

ENTRY_START = date(2026, 10, 1)
ENTRY_END = date(2026, 10, 10)
VOTING_START = date(2026, 10, 11)
VOTING_END = date(2026, 10, 18)
RESULTS_DATE = date(2026, 10, 20)
FINAL_DATE = date(2026, 10, 31)

#: Кнопка конкурса появляется в меню ботов за неделю до приёма заявок и
#: исчезает после финала: меню не должно расти навсегда из-за разовой затеи.
MENU_FROM = date(2026, 9, 24)
MENU_UNTIL = FINAL_DATE

CITY = "Томск"
MIN_AGE = 18
WINNERS = 3

PRIZE = "базовый тариф Руми на 6 месяцев"
#: Заполнить, когда организатор назовёт партнёров и площадку финала. Пока в
#: правилах и в боте этих обещаний нет вовсе — обещать неизвестное нельзя.
PARTNER_PRIZES: Optional[str] = None
FINAL_PLACE: Optional[str] = None

HASHTAG = "#красотаэторуми"
VK_GROUP_URL = "https://vk.ru/rrumii"

# ── анкета в боте ───────────────────────────────────────────────────────────
#: Четыре коротких вопроса. Больше — и человек бросит на середине; меньше —
#: и с победителем будет не связаться.
STEPS = (
    ("name", "Как вас зовут? Напишите имя и фамилию."),
    ("city", f"Из какого вы города? Конкурс идёт для мастеров города {CITY}."),
    ("work", "Пришлите ссылку на вашу работу в соцсети — пост или видео с образом."),
    ("contact", "Как с вами связаться? Телефон, почта или ник в соцсети."),
)

MAX_ANSWER = 300
MIN_ANSWER = 2


def is_menu_visible(today: Optional[date] = None) -> bool:
    today = today or date.today()
    return MENU_FROM <= today <= MENU_UNTIL


def accepts_entries(today: Optional[date] = None) -> bool:
    today = today or date.today()
    return ENTRY_START <= today <= ENTRY_END


def ru_date(value: date) -> str:
    months = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля",
              "августа", "сентября", "октября", "ноября", "декабря")
    return f"{value.day} {months[value.month - 1]}"


def short_pitch(today: Optional[date] = None) -> str:
    """Рассказ о конкурсе в боте — коротко и без обещаний, которых нет."""
    lines = [
        f"{TITLE}.",
        "",
        f"Задание: образ в стиле Хеллоуина. Выкладываете фото или видео работы "
        f"в свою соцсеть с хэштегом {HASHTAG} и отметкой Руми, а заявку "
        f"оставляете здесь, в боте.",
        "",
        f"Приём заявок: {ru_date(ENTRY_START)} — {ru_date(ENTRY_END)}.",
        f"Голосование подписчиков: {ru_date(VOTING_START)} — {ru_date(VOTING_END)}.",
        f"Кто прошёл дальше, объявим {ru_date(RESULTS_DATE)}.",
        f"Финал — {ru_date(FINAL_DATE)}: работу делают вживую, победителей "
        f"выбирают эксперты.",
        "",
        f"Приз победителям ({WINNERS} человека): {PRIZE}, отметка «Победитель "
        f"конкурса Руми» и место выше в каталоге на 3 месяца.",
    ]
    if not accepts_entries(today):
        lines += ["", entry_window_note(today)]
    return "\n".join(lines)


def entry_window_note(today: Optional[date] = None) -> str:
    today = today or date.today()
    if today < ENTRY_START:
        return f"Приём заявок начнётся {ru_date(ENTRY_START)}."
    return f"Приём заявок закончился {ru_date(ENTRY_END)}."


def validate_answer(step_key: str, text: str) -> Optional[str]:
    """None — ответ годится, иначе что сказать человеку."""
    value = (text or "").strip()
    if len(value) < MIN_ANSWER:
        return "Слишком коротко — напишите ответ чуть подробнее."
    if len(value) > MAX_ANSWER:
        return f"Слишком длинно: уместите в {MAX_ANSWER} символов."
    if step_key == "work" and not _looks_like_link(value):
        return ("Нужна ссылка на работу в соцсети — начните с http:// или https:// "
                "либо пришлите адрес вида vk.com/…")
    return None


def _looks_like_link(value: str) -> bool:
    low = value.lower()
    return low.startswith(("http://", "https://")) or any(
        marker in low for marker in ("vk.com", "vk.ru", "t.me", "instagram.com", "www.")
    )


def summary(answers: dict) -> str:
    """Что записали — показываем перед отправкой, чтобы можно было исправить."""
    labels = {"name": "Имя", "city": "Город", "work": "Работа", "contact": "Связь"}
    return "\n".join(f"{labels[key]}: {answers.get(key, '—')}" for key, _ in STEPS)


CONSENT_TEXT = (
    "Отправляя заявку, вы соглашаетесь с правилами конкурса и с обработкой "
    "ваших данных для его проведения."
)
SENT_TEXT = (
    "Заявка принята ✅ Мы свяжемся с вами по указанным контактам. "
    "Не забудьте выложить работу в соцсеть с хэштегом " + HASHTAG + "."
)


async def save_entry(db, *, answers: dict, channel, chat_id: Optional[int],
                     user=None, consent_version: str = "", request=None):
    """Сохранить заявку и записать согласие в журнал.

    Согласие пишем тем же журналом, что и на регистрации: если участник
    поспорит, у нас будет отметка о том, когда и каким способом он принял
    правила и согласился на обработку данных.
    """
    from app.models.models import ConsentDocument, ContestEntry

    entry = ContestEntry(
        contest=SLUG,
        user_id=getattr(user, "id", None),
        channel=channel,
        chat_id=chat_id,
        name=answers.get("name", "")[:MAX_ANSWER],
        city=answers.get("city", "")[:MAX_ANSWER],
        work_url=answers.get("work", "")[:MAX_ANSWER],
        contact=answers.get("contact", "")[:MAX_ANSWER],
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    try:
        from app.services.consent_service import record_consents

        await record_consents(
            db, documents=(ConsentDocument.CONTEST_RULES, ConsentDocument.PD_CONSENT),
            version=consent_version, source=f"contest:{channel.value}",
            user_id=getattr(user, "id", None),
            phone=getattr(user, "phone", None), request=request,
        )
    except Exception:  # заявку уже приняли — терять её из-за журнала нельзя
        import logging

        logging.getLogger(__name__).exception(
            "конкурс: согласие не записано по заявке %s", entry.id)
    return entry


async def already_applied(db, *, chat_id: Optional[int], user=None) -> bool:
    """Одна заявка с чата (и с аккаунта): повторные — это правки, а не
    новые участники, и разбирать их вручную никто не будет."""
    from sqlalchemy import or_, select

    from app.models.models import ContestEntry

    conditions = []
    if chat_id is not None:
        conditions.append(ContestEntry.chat_id == chat_id)
    if getattr(user, "id", None):
        conditions.append(ContestEntry.user_id == user.id)
    if not conditions:
        return False
    return (await db.execute(
        select(ContestEntry.id).where(ContestEntry.contest == SLUG, or_(*conditions))
    )).scalars().first() is not None


# ── анкета: состояние и шаги ────────────────────────────────────────────────
# Состояние держим в Redis, как у обращения в поддержку: боты перезапускаются
# вместе со стеком, и недописанная заявка не должна теряться от деплоя.

DRAFT_TTL = 1800
CANCEL_WORDS = ("отмена", "/cancel", "стоп")

#: Что бот показывает после ответов: сводка и две кнопки.
CMD_START = "contest:start"
CMD_APPLY = "contest:apply"
CMD_SEND = "contest:send"


def draft_key(channel, chat_id: int) -> str:
    return f"contest:draft:{getattr(channel, 'value', channel)}:{chat_id}"


async def draft_get(channel, chat_id: int) -> Optional[dict]:
    import json

    from app.core.limiter import get_redis

    raw = await get_redis().get(draft_key(channel, chat_id))
    if not raw:
        return None
    return json.loads(raw if isinstance(raw, str) else raw.decode())


async def draft_set(channel, chat_id: int, draft: dict) -> None:
    import json

    from app.core.limiter import get_redis

    await get_redis().set(draft_key(channel, chat_id), json.dumps(draft), ex=DRAFT_TTL)


async def draft_clear(channel, chat_id: int) -> None:
    from app.core.limiter import get_redis

    await get_redis().delete(draft_key(channel, chat_id))


def _question(index: int) -> str:
    key, text = STEPS[index]
    return f"Вопрос {index + 1} из {len(STEPS)}. {text}"


async def begin(db, channel, chat_id: int, user=None) -> str:
    """Начать анкету. Возвращает, что сказать человеку."""
    if not accepts_entries():
        return entry_window_note()
    if await already_applied(db, chat_id=chat_id, user=user):
        return ("Ваша заявка уже принята — спасибо! Если нужно что-то исправить, "
                f"напишите нам на {CONTACT_EMAIL}.")
    await draft_set(channel, chat_id, {"answers": {}, "step": 0})
    return (f"{_question(0)}\n\nОтменить можно в любой момент — напишите «отмена».")


async def answer(db, channel, chat_id: int, text: str) -> tuple[str, bool]:
    """Ответ на очередной вопрос. → (что сказать, показывать ли кнопку «Отправить»).

    Пустая строка в ответе означает «ничего не отвечаем»: так бывает, когда
    сообщение к анкете не относится.
    """
    draft = await draft_get(channel, chat_id)
    if draft is None:
        return "", False

    value = (text or "").strip()
    if value.lower() in CANCEL_WORDS:
        await draft_clear(channel, chat_id)
        return "Заявка отменена. Вернуться к ней можно в меню конкурса.", False

    index = int(draft.get("step", 0))
    key = STEPS[index][0]
    problem = validate_answer(key, value)
    if problem:
        return f"{problem}\n\n{_question(index)}", False

    draft["answers"][key] = value
    index += 1
    draft["step"] = index
    await draft_set(channel, chat_id, draft)

    if index < len(STEPS):
        return _question(index), False
    return (f"Проверьте заявку:\n\n{summary(draft['answers'])}\n\n{CONSENT_TEXT}", True)


async def send(db, channel, chat_id: int, user=None, consent_version: str = "",
               request=None) -> str:
    """Отправка заявки по кнопке. → что сказать человеку."""
    draft = await draft_get(channel, chat_id)
    if draft is None or len(draft.get("answers", {})) < len(STEPS):
        return "Заявка не заполнена — начните заново из меню конкурса."
    if await already_applied(db, chat_id=chat_id, user=user):
        await draft_clear(channel, chat_id)
        return "Ваша заявка уже принята — спасибо!"

    await save_entry(db, answers=draft["answers"], channel=channel, chat_id=chat_id,
                     user=user, consent_version=consent_version, request=request)
    await draft_clear(channel, chat_id)
    await _alert_admins(draft["answers"], channel)
    return SENT_TEXT


async def _alert_admins(answers: dict, channel) -> None:
    """Заявки редкие и срочные (конкурс идёт десять дней) — пусть админ
    узнаёт сразу, а не заходит проверять вкладку."""
    try:
        from app.db.session import AsyncSessionLocal
        from app.services.notifications import notify_admins

        async with AsyncSessionLocal() as db:
            await notify_admins(db, f"Заявка на конкурс: {answers.get('name', '')}",
                                f"{summary(answers)}\n\nИсточник: {getattr(channel, 'value', channel)}")
    except Exception:
        import logging

        logging.getLogger(__name__).exception("конкурс: админам не сообщили о заявке")
