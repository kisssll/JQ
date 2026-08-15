# app/services/model_matching_service.py
"""Общая логика мэтчинга «модель ↔ конкретная опубликованная услуга» —
используется и веб-страницами, и JSON-эндпоинтами
(app/api/v1/endpoints/model_matching.py).

Мэтч — состояние пары (model_user_id, service_id) в одной строке ModelMatch,
без отдельного лога свайпов: истории свайпов не требуется, а сам мэтч —
это переход состояния пары, а не независимое событие. Цена/длительность/
мастер берутся из Service — отдельного шага "оффер" нет: после мэтча модель
сразу выбирает реальный свободный слот в расписании мастера."""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Booking, Master, MasterPhoto, ModelMatch, ModelMatchStatus, ModelModerationStatus, ModelPhoto,
    Salon, SalonModerationStatus, Service, User,
)


async def count_booked_for_service(db: AsyncSession, service_id: int) -> int:
    """Сколько BOOKED-мэтчей уже набрала эта услуга — против неё сверяется квота."""
    return (await db.execute(
        select(func.count(ModelMatch.id)).where(
            ModelMatch.service_id == service_id, ModelMatch.status == ModelMatchStatus.BOOKED,
        )
    )).scalar() or 0


def is_service_open_for_models(service: Service, booked_count: int) -> bool:
    """Услуга открыта для новых мэтчей с моделями: ручной рубильник включён И
    (квота не задана ИЛИ ещё не набрана)."""
    if not service.model_seeking_open:
        return False
    if service.model_quota is not None and booked_count >= service.model_quota:
        return False
    return True


async def get_feed_cards(db: AsyncSession, model_user_id: int, limit: int = 10) -> list[dict]:
    """Опубликованные поиски (Service с is_model_practice=True), которые эта
    модель ещё не оценивала — карточка на конкретную услугу, не на мастера:
    у одного мастера может быть сразу несколько активных поисков."""
    already_decided = select(ModelMatch.service_id).where(
        ModelMatch.model_user_id == model_user_id,
        ModelMatch.model_liked.isnot(None),
    )
    result = await db.execute(
        select(Service, Master, Salon)
        .join(Master, Master.id == Service.master_id)
        .join(Salon, Salon.id == Master.salon_id)
        .where(
            Service.is_model_practice == True,  # noqa: E712
            Service.is_active == True,  # noqa: E712
            Service.model_seeking_open == True,  # noqa: E712
            Master.is_active == True,  # noqa: E712
            Salon.is_active == True,  # noqa: E712
            Salon.moderation_status == SalonModerationStatus.APPROVED,
            Salon.published_at.isnot(None),
            Salon.is_hidden == False,  # noqa: E712
            Service.id.notin_(already_decided),
        )
        .order_by(Service.id)
        .limit(limit * 2)  # с запасом — часть отсеется квотой ниже
    )
    cards = []
    for service, master, salon in result.all():
        if len(cards) >= limit:
            break
        booked_count = await count_booked_for_service(db, service.id)
        if not is_service_open_for_models(service, booked_count):
            continue
        master_user = (await db.execute(select(User).where(User.id == master.user_id))).scalar_one_or_none()
        photo_rows = (await db.execute(
            select(MasterPhoto).where(MasterPhoto.master_id == master.id).order_by(MasterPhoto.id)
        )).scalars().all()
        cards.append({
            "service_id": service.id,
            "service_name": service.name,
            "price": service.price,
            "duration_minutes": service.duration_minutes,
            "desired_date": service.model_desired_date.isoformat() if service.model_desired_date else None,
            "description": service.description or "",
            "master_id": master.id,
            "master_name": master_user.full_name if master_user else "Мастер",
            "specialization": master.specialization,
            "photo_url": master.photo_url,
            "photos": [p.url for p in photo_rows],
            "rating": master.rating,
            "salon_id": salon.id,
            "salon_name": salon.name,
            "salon_address": salon.address,
        })
    return cards


async def get_candidate_models(db: AsyncSession, service_id: int, limit: int = 10) -> list[dict]:
    """Анкеты моделей, которых ещё не оценили по ЭТОЙ КОНКРЕТНОЙ услуге —
    только прошедшие модерацию (см. ModelModerationStatus, тот же принцип,
    что у салонов)."""
    already_decided = select(ModelMatch.model_user_id).where(
        ModelMatch.service_id == service_id,
        ModelMatch.salon_liked.isnot(None),
    )
    result = await db.execute(
        select(User)
        .where(
            User.is_model == True,  # noqa: E712
            User.is_active == True,  # noqa: E712
            User.model_moderation_status == ModelModerationStatus.APPROVED,
            User.id.notin_(already_decided),
        )
        .order_by(User.id)
        .limit(limit)
    )
    models = result.scalars().all()
    photos_by_model: dict[int, list[str]] = {}
    if models:
        photo_rows = (await db.execute(
            select(ModelPhoto).where(ModelPhoto.model_user_id.in_([u.id for u in models])).order_by(ModelPhoto.id)
        )).scalars().all()
        for p in photo_rows:
            photos_by_model.setdefault(p.model_user_id, []).append(p.url)

    return [
        {
            "model_user_id": u.id,
            "name": u.full_name or "Модель",
            "city": u.city or "",
            "photo_url": u.model_photo_url,
            "photos": photos_by_model.get(u.id, []),
            "bio": u.model_bio or "",
            "looking_for": u.model_looking_for or "",
        }
        for u in models
    ]


async def get_invitations_for_model(db: AsyncSession, model_user_id: int) -> list[dict]:
    """Услуги, чей салон лайкнул модель первым — она ещё не ответила
    (salon_liked=True, model_liked ещё не проставлен). Отвечает тем же
    POST /feed/{service_id}/swipe, что и обычный свайп — это не новый флоу,
    просто предзаполненная карточка с приглашением."""
    result = await db.execute(
        select(ModelMatch, Service, Master, Salon)
        .join(Service, Service.id == ModelMatch.service_id)
        .join(Master, Master.id == ModelMatch.master_id)
        .join(Salon, Salon.id == Master.salon_id)
        .where(
            ModelMatch.model_user_id == model_user_id,
            ModelMatch.salon_liked == True,  # noqa: E712
            ModelMatch.model_liked.is_(None),
        )
        .order_by(ModelMatch.salon_liked_at.desc())
    )
    cards = []
    for match, service, master, salon in result.all():
        master_user = (await db.execute(select(User).where(User.id == master.user_id))).scalar_one_or_none()
        cards.append({
            "match_id": match.id,
            "service_id": service.id,
            "service_name": service.name,
            "price": service.price,
            "master_id": master.id,
            "master_name": master_user.full_name if master_user else "Мастер",
            "specialization": master.specialization,
            "photo_url": master.photo_url,
            "description": service.description or "",
            "salon_id": salon.id,
            "salon_name": salon.name,
            "salon_rating": salon.rating,
            "invited_at": match.salon_liked_at.isoformat() if match.salon_liked_at else None,
        })
    return cards


async def get_active_matches_for_model(db: AsyncSession, model_user_id: int) -> list[dict]:
    """Мэтчи модели в статусе MATCHED — взаимный лайк уже есть, осталось
    выбрать реальный слот в расписании мастера (см. accept-slot)."""
    result = await db.execute(
        select(ModelMatch, Service, Master, Salon)
        .join(Service, Service.id == ModelMatch.service_id)
        .join(Master, Master.id == ModelMatch.master_id)
        .join(Salon, Salon.id == Master.salon_id)
        .where(ModelMatch.model_user_id == model_user_id, ModelMatch.status == ModelMatchStatus.MATCHED)
        .order_by(ModelMatch.matched_at.desc())
    )
    cards = []
    for match, service, master, salon in result.all():
        master_user = (await db.execute(select(User).where(User.id == master.user_id))).scalar_one_or_none()
        cards.append({
            "match_id": match.id,
            "status": match.status.value.lower(),
            "service_id": service.id,
            "service_name": service.name,
            "price": service.price,
            "duration_minutes": service.duration_minutes,
            "master_id": master.id,
            "master_name": master_user.full_name if master_user else "Мастер",
            "salon_id": salon.id,
            "salon_name": salon.name,
        })
    return cards


async def get_history_for_model(db: AsyncSession, model_user_id: int) -> list[dict]:
    """Мэтчи, дошедшие до записи (BOOKED) — прошедшие и предстоящие визиты."""
    result = await db.execute(
        select(ModelMatch, Service, Master, Salon, Booking)
        .join(Service, Service.id == ModelMatch.service_id)
        .join(Master, Master.id == ModelMatch.master_id)
        .join(Salon, Salon.id == Master.salon_id)
        .outerjoin(Booking, Booking.id == ModelMatch.booking_id)
        .where(ModelMatch.model_user_id == model_user_id, ModelMatch.status == ModelMatchStatus.BOOKED)
        .order_by(ModelMatch.chosen_slot.desc())
    )
    history = []
    for match, service, master, salon, booking in result.all():
        master_user = (await db.execute(select(User).where(User.id == master.user_id))).scalar_one_or_none()
        history.append({
            "match_id": match.id,
            "service_name": service.name,
            "master_name": master_user.full_name if master_user else "Мастер",
            "salon_name": salon.name,
            "chosen_slot": match.chosen_slot.isoformat() if match.chosen_slot else None,
            "price": service.price,
            "booking_status": booking.status.value if booking else None,
        })
    return history


async def get_salon_matches(db: AsyncSession, salon_id: int) -> list[dict]:
    """Мэтчи салона для списка в бизнес-панели: взаимные (MATCHED/BOOKED/
    DECLINED) плюс те, где салон уже лайкнул модель, а она ещё не ответила
    (PENDING с salon_liked=True) — иначе такие лайки нигде не видны салону
    и выглядят как «мэтчей нет», хотя на самом деле салон ждёт ответа."""
    result = await db.execute(
        select(ModelMatch, Service, Master, User)
        .join(Service, Service.id == ModelMatch.service_id)
        .join(Master, Master.id == ModelMatch.master_id)
        .join(User, User.id == ModelMatch.model_user_id)
        .where(
            ModelMatch.salon_id == salon_id,
            (ModelMatch.status != ModelMatchStatus.PENDING) | (ModelMatch.salon_liked == True),  # noqa: E712
        )
        .order_by(ModelMatch.id.desc())
    )
    return [
        {
            "id": match.id,
            "status": "waiting" if match.status == ModelMatchStatus.PENDING else match.status.value.lower(),
            "service_id": service.id,
            "service_name": service.name,
            "price": service.price,
            "master_id": master.id,
            "master_name": master.specialization,
            "model_user_id": model_user.id,
            "model_name": model_user.full_name or "Модель",
            "chosen_slot": match.chosen_slot.isoformat() if match.chosen_slot else None,
        }
        for match, service, master, model_user in result.all()
    ]


async def _get_or_create_match(db: AsyncSession, *, model_user_id: int, service_id: int) -> ModelMatch:
    match = (await db.execute(
        select(ModelMatch).where(
            ModelMatch.model_user_id == model_user_id, ModelMatch.service_id == service_id,
        )
    )).scalar_one_or_none()
    if match is None:
        service = (await db.execute(select(Service).where(Service.id == service_id))).scalar_one()
        match = ModelMatch(
            model_user_id=model_user_id, service_id=service_id,
            master_id=service.master_id, salon_id=(await db.execute(
                select(Master.salon_id).where(Master.id == service.master_id)
            )).scalar_one(),
        )
        db.add(match)
        await db.flush()
    return match


async def record_swipe(
    db: AsyncSession, *, model_user_id: int, service_id: int, like: bool,
    actor: str, actor_id: int | None = None,
) -> tuple[ModelMatch, bool]:
    """Проставляет лайк/пасс с одной из сторон. actor: "model" | "salon".

    Возвращает (match, is_fresh_match) — is_fresh_match=True, если именно
    этим свайпом образовался взаимный мэтч (для отправки уведомления)."""
    match = await _get_or_create_match(db, model_user_id=model_user_id, service_id=service_id)
    now = datetime.now(timezone.utc)

    if actor == "model":
        match.model_liked = like
        match.model_liked_at = now
    else:
        match.salon_liked = like
        match.salon_liked_at = now
        match.salon_liked_by_id = actor_id

    is_fresh_match = False
    if match.status == ModelMatchStatus.PENDING and match.model_liked and match.salon_liked:
        match.status = ModelMatchStatus.MATCHED
        match.matched_at = now
        is_fresh_match = True

    await db.commit()
    await db.refresh(match)
    return match, is_fresh_match
