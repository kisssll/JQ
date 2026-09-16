# app/services/ad_consent.py
"""Согласие на рекламную рассылку вечерних окон со скидкой.

Почему отдельный модуль, а не просто переключатель темы. Подборка «успейте
записаться дешевле» — реклама. По ч. 1 ст. 18 закона «О рекламе» рассылать её
по сетям электросвязи можно только с ПРЕДВАРИТЕЛЬНОГО согласия, а доказывать,
что согласие было, обязан рекламодатель. Запись `evening_deals: true` в
настройках не доказывает ни когда, ни каким образом человек согласился.

Поэтому включить тему можно ТОЛЬКО через `grant()`: он пишет согласие в журнал
и ставит настройку одной транзакцией. Нет записи в журнале — нет и рассылки.

Общий `record_consents` для этого не годится намеренно: он глотает ошибки
записи («согласие уже дано, терять регистрацию нельзя»). Для регистрации это
правильно, для рекламы — наоборот: не смогли записать доказательство —
рассылку не включаем.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import ConsentDocument, User, UserConsent
from app.services.notifications import TOPIC_EVENING_DEALS

#: Редакция формулировки, с которой соглашается человек. Меняется текст
#: вопроса — меняется и версия: в журнале должно быть видно, на что именно
#: было дано согласие.
VERSION = "2026-09-16.2"

#: Вопрос отправляется один раз. Он НЕЙТРАЛЬНЫЙ: описывает, на что человек
#: соглашается, но не зазывает — без размера скидки, конкретных окон и ссылок.
#: Посыл — «запускаем»: подборка до перехода на согласие не уходила никому ни
#: разу (на проде 16.09.2026 не было ни одной включённой акции), и писать
#: «раньше присылали» было бы неправдой. Вопрос «хотите получать рекламу?» рекламой не является, а
#: «успейте на −30%, хотите ещё?» — уже является, и мы отправили бы ту самую
#: рекламу без согласия, которую этим модулем прекращаем.
QUESTION_TEXT = (
    "Мы запускаем подборку свободных вечерних окон в салонах, где на вечер "
    "действует скидка. Это рекламная рассылка, поэтому присылаем её только "
    "тем, кто сам на неё согласился.\n\n"
    "Если хотите получать подборку — нажмите кнопку ниже. Если нет — ничего "
    "делать не нужно, больше мы об этом не спросим.\n\n"
    "Уведомления о ваших записях это не затрагивает."
)
OPT_IN_LABEL = "Да, присылать подборку"
THANKS_TEXT = (
    "Готово, подборка вечерних окон будет приходить. Отключить её можно в "
    "любой момент в разделе «Мои уведомления»."
)

#: Отметка «уже спрашивали» в той же JSON-колонке настроек. Интерфейс настроек
#: перебирает темы, а не ключи колонки, поэтому отметку никто не увидит.
ASKED_KEY = "evening_deals_asked_at"

#: Ссылка из письма живёт месяц: дольше вопрос теряет смысл.
TOKEN_TTL_SECONDS = 30 * 24 * 3600


def is_consented(user: User | None) -> bool:
    return bool(user and (user.tg_notify_prefs or {}).get(TOPIC_EVENING_DEALS) is True)


def was_asked(user: User | None) -> bool:
    return bool(user and (user.tg_notify_prefs or {}).get(ASKED_KEY))


async def grant(
    db: AsyncSession, *, user_id: int, source: str, request=None,
) -> bool:
    """Записать согласие и включить рассылку. Одной транзакцией.

    Возвращает True, если согласие записано сейчас, False — если было и раньше
    (повторное нажатие кнопки не плодит записи в журнале).

    Ошибку записи НЕ глотает: нет доказательства — нет рассылки.
    """
    from app.services.consent_service import _client_ip

    user = await db.get(User, user_id)
    if user is None:
        raise ValueError(f"пользователь {user_id} не найден")
    if is_consented(user):
        return False

    ua = (request.headers.get("user-agent") if request else "") or ""
    db.add(UserConsent(
        user_id=user.id,
        phone=(user.phone or None) and user.phone[:32],
        document=ConsentDocument.ADS_EVENING_DEALS,
        version=VERSION,
        source=source[:64],
        ip=_client_ip(request),
        user_agent=ua[:512] or None,
    ))
    # JSON-колонку меняем пересозданием словаря — мутацию на месте
    # SQLAlchemy не заметит и ничего не сохранит.
    prefs = dict(user.tg_notify_prefs or {})
    prefs[TOPIC_EVENING_DEALS] = True
    user.tg_notify_prefs = prefs
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return True


async def revoke(db: AsyncSession, *, user_id: int) -> None:
    """Выключить рассылку. Для отзыва доказательство не нужно — просто перестаём."""
    user = await db.get(User, user_id)
    if user is None:
        return
    prefs = dict(user.tg_notify_prefs or {})
    prefs[TOPIC_EVENING_DEALS] = False
    user.tg_notify_prefs = prefs
    await db.commit()


def mark_asked(user: User) -> None:
    """Поставить отметку «спрашивали». Коммит — на вызывающем коде."""
    prefs = dict(user.tg_notify_prefs or {})
    prefs[ASKED_KEY] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    user.tg_notify_prefs = prefs


def unmark_asked(user: User) -> None:
    """Снять отметку, если вопрос так и не ушёл, — чтобы его можно было повторить."""
    prefs = dict(user.tg_notify_prefs or {})
    prefs.pop(ASKED_KEY, None)
    user.tg_notify_prefs = prefs


# ── ссылка из письма ─────────────────────────────────────────────────────────

def _sign(payload: str) -> str:
    key = f"ad-consent:{settings.SECRET_KEY}".encode()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def make_token(user_id: int, now: float | None = None) -> str:
    """Подписанная метка для ссылки в письме: кто и до какого момента.

    Ссылка сама по себе согласия НЕ даёт — она лишь открывает страницу с
    кнопкой. Почтовые сканеры и превью открывают ссылки из писем заранее, и
    если бы переход записывал согласие, в журнале оказалось бы согласие,
    данное роботом за человека.
    """
    expires = int((now if now is not None else time.time()) + TOKEN_TTL_SECONDS)
    payload = f"{user_id}.{expires}"
    return f"{payload}.{_sign(payload)}"


def read_token(token: str, now: float | None = None) -> int | None:
    """user_id из метки или None, если метка поддельная или просрочена."""
    try:
        user_part, expires_part, signature = (token or "").split(".")
        payload = f"{user_part}.{expires_part}"
        if not hmac.compare_digest(signature, _sign(payload)):
            return None
        if int(expires_part) < (now if now is not None else time.time()):
            return None
        return int(user_part)
    except (ValueError, TypeError):
        return None
