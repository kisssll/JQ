# app/services/notifications.py
"""Уведомления в Telegram (бот @rumi_beauty_bot + очередь ARQ).

Маршрутизация — НЕ по полю User.role (оно рассинхронизировано с
реальностью), а по фактическим связям и матрице прав салона:
- клиент события — по booking.client_id;
- мастер — по связи Master.user_id;
- команда салона — активные SalonMember, у кого есть ПРАВО на тему
  (manage_schedule → записи, manage_inventory → заявки склада,
  manage_reviews → отзывы и жалобы на фото); создатель салона получает
  всё (is_creator обходит матрицу — как в check_salon_permission).

Каждой стороне — свой текст. Один человек может быть сразу клиентом,
мастером и владельцем — он получит каждое уведомление один раз (дедуп
по chat_id, приоритет более специфичной роли).

Доставка идёт в канал пользователя (Telegram, MAX или почта — см.
services/notify_channel.py); если канала нет, уведомление тихо не уходит.
Любая ошибка глотается с логом: уведомления — сервис вежливости, они
не имеют права ломать бизнес-действие, которое их породило.
"""
import logging
from datetime import datetime, timedelta, timezone
from app.utils.timezone import localize_time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.worker import get_arq_pool
from app.services.notify_channel import (
    has_channel,
    has_channel_clause,
    resolve as resolve_channel,
    task_for as task_for_channel,
)
from app.models.models import (
    Booking,
    Master,
    ModelMatch,
    NotifyChannel,
    Review,
    ReviewTargetType,
    Salon,
    SalonChainRequest,
    SalonMember,
    Service,
    User,
    UserRole,
    WarehouseRequest,
    WarehouseRequestStatus,
    WarehouseRequestType,
)

logger = logging.getLogger(__name__)

REMINDER_BEFORE = timedelta(hours=2)

# Темы личных подписок (users.tg_notify_prefs). Ключи стабильные — на них
# завязаны кнопки в боте (app/tg_bot.py) и сохранённые настройки.
TOPIC_BOOKINGS = "bookings"
TOPIC_REMINDERS = "reminders"
TOPIC_WAREHOUSE = "warehouse"
TOPIC_REVIEWS = "reviews"
TOPIC_REPORTS = "reports"
TOPIC_MODELS = "models"
TOPIC_EVENING_DEALS = "evening_deals"  # клиентская рассылка вечерних окон со скидкой

TOPIC_LABELS = {
    TOPIC_BOOKINGS: "Записи (новые и отмены)",
    TOPIC_REMINDERS: "Напоминания о визите",
    TOPIC_EVENING_DEALS: "Вечерние скидки",
    TOPIC_WAREHOUSE: "Склад и заявки",
    TOPIC_REVIEWS: "Отзывы",
    TOPIC_REPORTS: "Жалобы на фото",
    TOPIC_MODELS: "Модельный мэтчинг",
}


def wants(user: User | None, topic: str) -> bool:
    """Личная подписка: нет настройки — включено (opt-out, не opt-in)."""
    if user is None:
        return False
    prefs = user.tg_notify_prefs or {}
    return bool(prefs.get(topic, True))


async def _members_with_permission(
    db: AsyncSession, salon_id: int, permission: str
) -> list[User]:
    """Пользователи с Telegram, кому по матрице прав положена эта тема.

    Создатель салона получает всё (как в check_salon_permission). Право
    настраивается владельцем в UI сотрудников — тем самым он управляет
    и тем, кому приходят уведомления, отдельной настройки не нужно.
    """
    rows = (
        await db.execute(
            select(User, SalonMember)
            .join(SalonMember, SalonMember.user_id == User.id)
            .where(
                SalonMember.salon_id == salon_id,
                SalonMember.is_active == True,  # noqa: E712
                has_channel_clause(),
            )
        )
    ).all()
    return [
        user for user, member in rows
        if member.is_creator or bool((member.permissions or {}).get(permission))
    ]


class _Fanout:
    """Отправка с дедупом по пользователю: первый (более специфичный) текст
    побеждает. Дедуп именно по user.id, а не по chat_id — у пользователя
    теперь может быть несколько адресов (TG/MAX/почта)."""

    def __init__(self) -> None:
        self._sent: set[int] = set()

    async def send(self, user: User | None, text: str, topic: str | None = None) -> None:
        if user is None or user.id in self._sent:
            return
        if topic is not None and not wants(user, topic):
            return
        if await deliver(user, text):
            self._sent.add(user.id)


def reminder_eta_utc(start_naive: datetime, salon_tz: str) -> datetime | None:
    """UTC-момент напоминания (за REMINDER_BEFORE до начала), либо None.

    start_time хранится naive в местном времени салона — локализуем через
    zoneinfo и переводим в UTC; если момент уже в прошлом, напоминание
    не ставим (запись «на через час» получает только подтверждение).
    """
    aware = localize_time(start_naive, salon_tz)
    eta = aware.astimezone(timezone.utc) - REMINDER_BEFORE
    return eta if eta > datetime.now(timezone.utc) else None


async def _booking_context(db: AsyncSession, booking: Booking) -> dict:
    """Все стороны записи одним заходом (явные select — без ленивой подгрузки)."""
    master = (
        await db.execute(select(Master).where(Master.id == booking.master_id))
    ).scalar_one()
    salon = (
        await db.execute(select(Salon).where(Salon.id == master.salon_id))
    ).scalar_one()
    service = (
        await db.execute(select(Service).where(Service.id == booking.service_id))
    ).scalar_one_or_none()
    client = (
        await db.execute(select(User).where(User.id == booking.client_id))
    ).scalar_one_or_none()
    master_user = (
        await db.execute(select(User).where(User.id == master.user_id))
    ).scalar_one_or_none()
    return {
        "master": master, "salon": salon, "service": service,
        "client": client, "master_user": master_user,
    }


async def deliver(user: User | None, text: str, subject: str = "Руми", **kwargs) -> bool:
    """Доставка одного уведомления пользователю в ЕГО канал (TG/MAX/почта).

    Раньше здесь был прямой enqueue в Telegram, поэтому обладатели MAX и почты
    не получали ничего. Теперь канал резолвится (см. notify_channel.resolve),
    а если достучаться некуда — тихо логируем и возвращаем False: отсутствие
    канала не должно ронять действие пользователя.
    """
    channel, address = resolve_channel(user)
    if address is None:
        logger.info(
            "уведомление не доставлено (нет канала): user=%s",
            getattr(user, "id", "?"),
        )
        return False

    pool = await get_arq_pool()
    if channel == NotifyChannel.EMAIL:
        await pool.enqueue_job("send_email", address, subject, text, **kwargs)
    else:
        await pool.enqueue_job(task_for_channel(channel), address, text, **kwargs)
    return True


async def notify_booking_created(db: AsyncSession, booking: Booking) -> None:
    await _salon_booking_email(db, booking, "created")  # копия на почту салона (не зависит от TG)
    if not settings.TG_NOTIFY_ENABLED:
        return
    try:
        ctx = await _booking_context(db, booking)
        salon, service, client = ctx["salon"], ctx["service"], ctx["client"]
        when = booking.start_time.strftime("%d.%m в %H:%M")
        service_name = service.name if service else "услуга"
        client_name = (client.full_name or "клиент") if client else "клиент"
        master_name = (
            ctx["master_user"].full_name if ctx["master_user"] and ctx["master_user"].full_name
            else "мастер"
        )

        fanout = _Fanout()
        # Порядок = приоритет текста при совпадении людей: клиент → мастер → команда
        await fanout.send(
            client,
            f"✅ Вы записаны: {service_name} в «{salon.name}»\n"
            f"{when}, мастер {master_name}\n"
            f"Адрес: {salon.address or 'уточните у салона'}",
            topic=TOPIC_BOOKINGS,
        )
        await fanout.send(
            ctx["master_user"],
            f"📅 К вам новая запись: {client_name} — {service_name}\n{when}",
            topic=TOPIC_BOOKINGS,
        )
        for member in await _members_with_permission(db, salon.id, "manage_schedule"):
            await fanout.send(
                member,
                f"📅 Новая запись в «{salon.name}»: {client_name} — {service_name}\n"
                f"{when}, мастер {master_name}",
                topic=TOPIC_BOOKINGS,
            )

        if has_channel(client):
            eta = reminder_eta_utc(booking.start_time, salon.timezone)
            if eta:
                pool = await get_arq_pool()
                await pool.enqueue_job(
                    "send_booking_reminder", booking.id,
                    _defer_until=eta,
                    _job_id=f"booking-reminder:{booking.id}",
                )
    except Exception:
        logger.exception("notify_booking_created(%s): уведомления не поставлены", booking.id)


async def notify_booking_cancelled(db: AsyncSession, booking: Booking) -> None:
    await _salon_booking_email(db, booking, "cancelled")  # копия на почту салона (не зависит от TG)
    if not settings.TG_NOTIFY_ENABLED:
        return
    try:
        ctx = await _booking_context(db, booking)
        salon = ctx["salon"]
        when = booking.start_time.strftime("%d.%m в %H:%M")
        service_name = ctx["service"].name if ctx["service"] else "услуга"

        fanout = _Fanout()
        await fanout.send(
            ctx["client"],
            f"❌ Ваша запись отменена: {service_name} в «{salon.name}», {when}",
            topic=TOPIC_BOOKINGS,
        )
        await fanout.send(
            ctx["master_user"],
            f"❌ Запись к вам отменена: {service_name}, {when}",
            topic=TOPIC_BOOKINGS,
        )
        for member in await _members_with_permission(db, salon.id, "manage_schedule"):
            await fanout.send(
                member, f"❌ Запись отменена в «{salon.name}»: {service_name}, {when}",
                topic=TOPIC_BOOKINGS,
            )
    except Exception:
        logger.exception("notify_booking_cancelled(%s): уведомления не поставлены", booking.id)


# ── Заявки склада (manage_inventory) ─────────────────────────────────────────

_REQUEST_TYPE_LABEL = {
    WarehouseRequestType.CONSUMABLE_LOW: "заканчивается расходник",
    WarehouseRequestType.EQUIPMENT_BROKEN: "сломана/нужна техника",
}


async def notify_warehouse_request_created(db: AsyncSession, request: WarehouseRequest) -> None:
    """Мастер подал заявку → тем, кто управляет складом салона."""
    if not settings.TG_NOTIFY_ENABLED:
        return
    try:
        from app.models.models import Equipment, InventoryItem

        subject_name = "позиция"
        if request.item_id:
            item = (
                await db.execute(select(InventoryItem).where(InventoryItem.id == request.item_id))
            ).scalar_one_or_none()
            subject_name = item.name if item else subject_name
        elif request.equipment_id:
            eq = (
                await db.execute(select(Equipment).where(Equipment.id == request.equipment_id))
            ).scalar_one_or_none()
            subject_name = eq.name if eq else subject_name

        author = (
            await db.execute(select(User).where(User.id == request.created_by_id))
        ).scalar_one_or_none()
        author_name = (author.full_name or "мастер") if author else "мастер"
        label = _REQUEST_TYPE_LABEL.get(request.type, "заявка")

        # Два личных фильтра поверх права manage_inventory:
        # 1) SalonMember.notify_warehouse_requests — тумблер ЭТОГО салона
        #    (переключается во вкладке «Склад» панели, идея руководителя);
        # 2) тема TOPIC_WAREHOUSE в боте — глобальный выключатель человека.
        rows = (
            await db.execute(
                select(User, SalonMember)
                .join(SalonMember, SalonMember.user_id == User.id)
                .where(
                    SalonMember.salon_id == request.salon_id,
                    SalonMember.is_active == True,  # noqa: E712
                    SalonMember.notify_warehouse_requests == True,  # noqa: E712
                    has_channel_clause(),
                )
            )
        ).all()
        fanout = _Fanout()
        for member_user, member in rows:
            if not (member.is_creator or bool((member.permissions or {}).get("manage_inventory"))):
                continue
            await fanout.send(
                member_user,
                f"📦 Заявка от {author_name}: {label} — «{subject_name}»"
                + (f"\nКомментарий: {request.comment}" if request.comment else ""),
                topic=TOPIC_WAREHOUSE,
            )
    except Exception:
        logger.exception("notify_warehouse_request_created(%s): не поставлено", request.id)


async def notify_warehouse_request_resolved(db: AsyncSession, request: WarehouseRequest) -> None:
    """Заявку разобрали → автору-мастеру."""
    if not settings.TG_NOTIFY_ENABLED:
        return
    try:
        author = (
            await db.execute(select(User).where(User.id == request.created_by_id))
        ).scalar_one_or_none()
        verdict = (
            "✅ выполнена" if request.status == WarehouseRequestStatus.RESOLVED
            else "❌ отклонена"
        )
        await _Fanout().send(author, f"📦 Ваша заявка на склад {verdict}", topic=TOPIC_WAREHOUSE)
    except Exception:
        logger.exception("notify_warehouse_request_resolved(%s): не поставлено", request.id)


# ── Отзывы и жалобы (manage_reviews) ─────────────────────────────────────────

async def notify_new_review(db: AsyncSession, review: Review) -> None:
    """Новый отзыв → команде с manage_reviews; о мастере — ещё и самому мастеру."""
    if not settings.TG_NOTIFY_ENABLED:
        return
    try:
        salon = (
            await db.execute(select(Salon).where(Salon.id == review.salon_id))
        ).scalar_one_or_none()
        if salon is None:
            return
        stars = "★" * int(review.rating) + "☆" * (5 - int(review.rating))
        verified = "подтверждён визитом" if review.is_verified else "без подтверждения визита"

        fanout = _Fanout()
        if review.target_type == ReviewTargetType.MASTER and review.master_id:
            master_user = (
                await db.execute(
                    select(User).join(Master, Master.user_id == User.id)
                    .where(Master.id == review.master_id)
                )
            ).scalar_one_or_none()
            await fanout.send(
                master_user, f"⭐ Новый отзыв о вас: {stars} ({verified})",
                topic=TOPIC_REVIEWS,
            )
        for member in await _members_with_permission(db, salon.id, "manage_reviews"):
            await fanout.send(
                member, f"⭐ Новый отзыв в «{salon.name}»: {stars} ({verified})",
                topic=TOPIC_REVIEWS,
            )
    except Exception:
        logger.exception("notify_new_review(%s): не поставлено", review.id)


async def notify_admins(db: AsyncSession, subject: str, body: str = "") -> None:
    """Алерт платформенным админам о событии, требующем их действия:
    Telegram всем ADMIN с привязкой + письмо на ADMIN_ALERT_EMAIL (hello@).

    Это админ-обязанность, поэтому личные mute-подписки НЕ учитываются
    (в отличие от тематических уведомлений через _Fanout).
    """
    text = subject if not body else f"{subject}\n{body}"
    try:
        pool = await get_arq_pool()
        admins = (await db.execute(
            select(User).where(User.role == UserRole.ADMIN, has_channel_clause())
        )).scalars().all()
        seen: set[int] = set()
        for admin in admins:
            if admin.id in seen:
                continue
            seen.add(admin.id)
            await deliver(admin, f"🛡️ {text}", subject=f"[Руми] {subject}")
        if settings.ADMIN_ALERT_EMAIL:
            await pool.enqueue_job(
                "send_email", settings.ADMIN_ALERT_EMAIL, f"[Руми] {subject}", body or subject
            )
    except Exception:
        logger.exception("notify_admins: не удалось разослать алерт (%s)", subject)


async def notify_photo_report(db: AsyncSession, salon_id: int | None) -> None:
    """Жалоба на фото → модераторам салона (платформенных админов покрывает
    notify_admins из ручки создания жалобы)."""
    if not settings.TG_NOTIFY_ENABLED:
        return
    try:
        fanout = _Fanout()
        if salon_id is not None:
            for member in await _members_with_permission(db, salon_id, "manage_reviews"):
                await fanout.send(member, "🚩 Новая жалоба на фото — загляните в модерацию", topic=TOPIC_REPORTS)
    except Exception:
        logger.exception("notify_photo_report: не поставлено")


# ── Модельный мэтчинг (manage_masters) ───────────────────────────────────────

async def notify_model_match(db: AsyncSession, match: ModelMatch) -> None:
    """Взаимный лайк по конкретной услуге → модели и команде салона с
    manage_masters. Цена/услуга уже известны из мэтча (нет отдельного
    оффера) — моделе сразу можно выбирать время в личном кабинете."""
    if not settings.TG_NOTIFY_ENABLED:
        return
    try:
        model_user = (await db.execute(select(User).where(User.id == match.model_user_id))).scalar_one_or_none()
        master = (await db.execute(select(Master).where(Master.id == match.master_id))).scalar_one_or_none()
        salon = (await db.execute(select(Salon).where(Salon.id == match.salon_id))).scalar_one_or_none()
        service = (await db.execute(select(Service).where(Service.id == match.service_id))).scalar_one_or_none()
        if salon is None:
            return
        master_user = (
            await db.execute(select(User).where(User.id == master.user_id))
        ).scalar_one_or_none() if master else None
        master_name = (master_user.full_name if master_user and master_user.full_name else "мастер")
        model_name = (model_user.full_name if model_user and model_user.full_name else "модель")
        service_name = service.name if service else "услугу"
        price_str = "бесплатно" if not service or not service.price else f"{service.price} ₽"

        fanout = _Fanout()
        await fanout.send(
            model_user,
            f"🎉 Мэтч! Мастер {master_name} из «{salon.name}» готов сделать вам «{service_name}» ({price_str}) "
            f"— выберите время в личном кабинете",
            topic=TOPIC_MODELS,
        )
        for member in await _members_with_permission(db, salon.id, "manage_masters"):
            await fanout.send(
                member,
                f"🎉 Модель {model_name} откликнулась на «{service_name}» у мастера {master_name} — взаимный мэтч!",
                topic=TOPIC_MODELS,
            )
    except Exception:
        logger.exception("notify_model_match(%s): не поставлено", match.id)


# ── Сеть салонов (объединение по единогласному согласию создателей) ─────────

async def _creators_for_salons(db: AsyncSession, salon_ids: list[int]) -> list[User]:
    rows = (
        await db.execute(
            select(User)
            .join(SalonMember, SalonMember.user_id == User.id)
            .where(
                SalonMember.salon_id.in_(salon_ids),
                SalonMember.is_creator == True,  # noqa: E712
                SalonMember.is_active == True,  # noqa: E712
                has_channel_clause(),
            )
        )
    ).scalars().all()
    return list(rows)


async def notify_chain_request_created(db: AsyncSession, request: SalonChainRequest) -> None:
    """Новый запрос на объединение в сеть → создателям всех затронутых
    салонов, КРОМЕ инициатора (он и так знает — сам отправил)."""
    if not settings.TG_NOTIFY_ENABLED:
        return
    try:
        from_salon = (await db.execute(select(Salon).where(Salon.id == request.from_salon_id))).scalar_one_or_none()
        if from_salon is None:
            return
        other_ids = [sid for sid in request.salon_ids if sid != request.from_salon_id]
        fanout = _Fanout()
        for creator in await _creators_for_salons(db, other_ids):
            await fanout.send(
                creator,
                f"🔗 Салон «{from_salon.name}» предлагает объединиться в сеть — решите в панели, "
                f"вкладка «Редактировать салон»",
            )
    except Exception:
        logger.exception("notify_chain_request_created(%s): не поставлено", request.id)


async def notify_chain_request_resolved(db: AsyncSession, request: SalonChainRequest) -> None:
    """Запрос закрыт (принят/отклонён) → создателям всех затронутых салонов."""
    if not settings.TG_NOTIFY_ENABLED:
        return
    try:
        from_salon = (await db.execute(select(Salon).where(Salon.id == request.from_salon_id))).scalar_one_or_none()
        to_salon = (await db.execute(select(Salon).where(Salon.id == request.to_salon_id))).scalar_one_or_none()
        if from_salon is None or to_salon is None:
            return
        verdict = "объединены в сеть 🎉" if request.status.value == "accepted" else "не объединены — кто-то отклонил запрос"
        text = f"🔗 «{from_salon.name}» и «{to_salon.name}»: {verdict}"
        fanout = _Fanout()
        for creator in await _creators_for_salons(db, request.salon_ids):
            await fanout.send(creator, text)
    except Exception:
        logger.exception("notify_chain_request_resolved(%s): не поставлено", request.id)


async def send_guest_booking_email(
    db: AsyncSession, booking, base_url: str, title: str, intro: str,
) -> None:
    """Брендированное письмо гостю (гостевая бронь без регистрации) со ссылкой
    отслеживания статуса записи. Тихо выходит, если email не оставляли.
    base_url — внешний адрес сайта (из request.base_url), нужен для абсолютной
    ссылки на страницу управления бронью /guest-booking/<token>."""
    if not getattr(booking, "guest_email", None):
        return
    try:
        from app.models.models import Service, Master, Salon
        from app.services.email_templates import booking_status_email

        service = (await db.execute(select(Service).where(Service.id == booking.service_id))).scalar_one_or_none()
        master = (await db.execute(select(Master).where(Master.id == booking.master_id))).scalar_one_or_none()
        salon = (await db.execute(select(Salon).where(Salon.id == master.salon_id))).scalar_one_or_none() if master else None

        when = booking.start_time.strftime("%d.%m.%Y %H:%M") if booking.start_time else "—"
        track_url = None
        if booking.guest_manage_token:
            base = (base_url or "").rstrip("/").replace("http://", "https://")
            track_url = f"{base}/guest-booking/{booking.guest_manage_token}"

        plain, html = booking_status_email(
            title=title, intro=intro,
            salon_name=salon.name if salon else "—",
            service_name=service.name if service else "—",
            when=when, track_url=track_url,
        )
        pool = await get_arq_pool()
        await pool.enqueue_job("send_email", booking.guest_email, f"{title} — Руми", plain, html)
    except Exception:
        logger.exception("send_guest_booking_email(booking=%s): не поставлено", getattr(booking, "id", "?"))


async def send_employee_credentials_email(db: AsyncSession, salon, name: str, login: str, password: str):
    """Отправляет реквизиты входа нового сотрудника на почту салона.
    Возвращает адрес, на который отправлено, либо None (если почта не задана).
    Исключения НЕ глотаем — вызывающий эндпоинт сообщает об успехе/ошибке."""
    if salon is None or not salon.email:
        return None
    from app.services.email_templates import credentials_email
    plain, html = credentials_email(name=name, login=login, password=password, salon_name=salon.name)
    pool = await get_arq_pool()
    await pool.enqueue_job("send_email", salon.email, f"Реквизиты для входа — {salon.name} — Руми", plain, html)
    return salon.email


async def _salon_booking_email(db: AsyncSession, booking, kind: str) -> None:
    """Копия уведомления о записи/отмене на почту салона (если задана).
    kind: 'created' | 'cancelled'. Тихо выходит без почты салона."""
    try:
        from app.models.models import Service, Master, Salon, User
        from app.services.email_templates import booking_status_email
        master = (await db.execute(select(Master).where(Master.id == booking.master_id))).scalar_one_or_none()
        salon = (await db.execute(select(Salon).where(Salon.id == master.salon_id))).scalar_one_or_none() if master else None
        if salon is None or not salon.email:
            return
        service = (await db.execute(select(Service).where(Service.id == booking.service_id))).scalar_one_or_none()
        client = (await db.execute(select(User).where(User.id == booking.client_id))).scalar_one_or_none()
        master_user = (await db.execute(select(User).where(User.id == master.user_id))).scalar_one_or_none() if master else None
        when = booking.start_time.strftime("%d.%m.%Y %H:%M") if booking.start_time else "—"
        client_name = client.full_name if client and client.full_name else "клиент"
        master_name = master_user.full_name if master_user and master_user.full_name else "мастер"
        if kind == "created":
            title = "Новая запись"
            intro = f"Клиент {client_name} записался к мастеру {master_name}. Подробности — в панели салона."
        else:
            title = "Запись отменена"
            intro = f"Запись клиента {client_name} к мастеру {master_name} отменена."
        plain, html = booking_status_email(
            title=title, intro=intro, salon_name=salon.name,
            service_name=service.name if service else "—", when=when, track_url=None,
        )
        pool = await get_arq_pool()
        await pool.enqueue_job("send_email", salon.email, f"{title} — {salon.name} — Руми", plain, html)
    except Exception:
        logger.exception("_salon_booking_email(%s): не поставлено", getattr(booking, "id", "?"))


# ── Подписка и тариф ─────────────────────────────────────────────────────────

async def notify_subscription(db: AsyncSession, salon, text: str) -> None:
    """Сообщение владельцу салона о его подписке.

    Шлём создателю салона: тариф и деньги — его зона, а не всей команды.
    Тема личных подписок здесь не проверяется: это не «сервис вежливости», а
    предупреждение о том, что салон вот-вот пропадёт из каталога.
    """
    try:
        owner = (await db.execute(
            select(User).where(User.id == salon.creator_id)
        )).scalar_one_or_none()
        await deliver(owner, f"💳 «{salon.name}»: {text}", subject="Тариф — Руми")
    except Exception:
        logger.exception("notify_subscription(salon=%s): не отправлено", getattr(salon, "id", "?"))


async def notify_model_subscription(db: AsyncSession, user, text: str) -> None:
    """То же для тарифа «модели» — плательщик сам пользователь."""
    try:
        await deliver(user, f"💳 {text}", subject="Тариф — Руми")
    except Exception:
        logger.exception("notify_model_subscription(user=%s): не отправлено", getattr(user, "id", "?"))
