# app/services/salon_chain_service.py
"""Сеть салонов: объединение независимых салонов (разные владельцы) в одну
сеть с общим брендом. Запрос на объединение требует единогласного согласия
создателя КАЖДОГО затронутого салона с обеих сторон — если у салона(ов) уже
есть сеть, объединяются все её участники, а не только два выбранных салона.

Голосует именно СОЗДАТЕЛЬ салона (SalonMember.is_creator) — это решение о
бренде салона, не операционное право, поэтому не делегируется через
manage_owners (см. тот же принцип для скрытия/удаления салона в business.py).
"""
from datetime import datetime, timezone as _tz

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Salon, SalonChain, SalonChainRequest, SalonChainRequestStatus, SalonChainVote


class SalonChainError(Exception):
    """Ожидаемая бизнес-ошибка (плохой запрос) — не 500, эндпоинт сам решает код ответа."""


async def _affected_salon_ids(db: AsyncSession, from_salon: Salon, to_salon: Salon) -> list[int]:
    """Union салонов обеих сторон: если у салона уже есть сеть — все её
    участники, иначе только сам салон."""
    ids: set[int] = {from_salon.id, to_salon.id}
    for salon in (from_salon, to_salon):
        if salon.chain_id is not None:
            rows = (await db.execute(select(Salon.id).where(Salon.chain_id == salon.chain_id))).scalars().all()
            ids.update(rows)
    return sorted(ids)


async def _execute_merge(db: AsyncSession, request: SalonChainRequest) -> SalonChain:
    """Все проголосовали «за» — реально объединяем салоны в одну сеть."""
    from_salon = (await db.execute(select(Salon).where(Salon.id == request.from_salon_id))).scalar_one()
    to_salon = (await db.execute(select(Salon).where(Salon.id == request.to_salon_id))).scalar_one()

    # Сохраняем существующую сеть одной из сторон (приоритет — у целевого
    # салона), чтобы не терять её имя; если обе стороны были без сети —
    # создаём новую с именем салона-инициатора (переименовать можно позже).
    target_chain_id = to_salon.chain_id or from_salon.chain_id
    losing_chain_id = None
    if target_chain_id is not None:
        target_chain = (await db.execute(select(SalonChain).where(SalonChain.id == target_chain_id))).scalar_one()
        other_id = from_salon.chain_id if target_chain_id == to_salon.chain_id else to_salon.chain_id
        if other_id is not None and other_id != target_chain_id:
            losing_chain_id = other_id
    else:
        target_chain = SalonChain(name=from_salon.name)
        db.add(target_chain)
        await db.flush()

    await db.execute(update(Salon).where(Salon.id.in_(request.salon_ids)).values(chain_id=target_chain.id))

    if losing_chain_id is not None:
        remaining = (await db.execute(select(Salon.id).where(Salon.chain_id == losing_chain_id))).scalars().all()
        if not remaining:
            losing_chain = (await db.execute(select(SalonChain).where(SalonChain.id == losing_chain_id))).scalar_one_or_none()
            if losing_chain is not None:
                await db.delete(losing_chain)

    return target_chain


async def _pending_requests_touching(db: AsyncSession, salon_ids) -> list[SalonChainRequest]:
    """Активные (PENDING) запросы, чей состав пересекается с salon_ids.
    salon_ids хранится JSON-массивом, поэтому фильтруем в Python."""
    wanted = set(salon_ids)
    pending = (await db.execute(
        select(SalonChainRequest).where(SalonChainRequest.status == SalonChainRequestStatus.PENDING)
    )).scalars().all()
    return [r for r in pending if wanted & set(r.salon_ids)]


async def create_request(db: AsyncSession, initiator_user_id: int, from_salon: Salon, to_salon: Salon) -> SalonChainRequest:
    if from_salon.id == to_salon.id:
        raise SalonChainError("Нельзя объединить салон сам с собой")
    if to_salon.chain_id is not None and from_salon.chain_id == to_salon.chain_id:
        raise SalonChainError("Эти салоны уже в одной сети")

    salon_ids = await _affected_salon_ids(db, from_salon, to_salon)

    # Не допускаем пересекающиеся активные запросы: иначе состав сети мог бы
    # измениться другим слиянием между созданием этого запроса и его
    # исполнением, и merge ушёл бы по устаревшему salon_ids. Один активный
    # запрос на салон за раз — состав фиксирован на время голосования.
    if await _pending_requests_touching(db, salon_ids):
        raise SalonChainError("По одному из этих салонов уже есть активный запрос на объединение — дождитесь его завершения")

    creators = dict((await db.execute(
        select(Salon.id, Salon.creator_id).where(Salon.id.in_(salon_ids))
    )).all())

    request = SalonChainRequest(
        initiator_user_id=initiator_user_id,
        from_salon_id=from_salon.id,
        to_salon_id=to_salon.id,
        salon_ids=salon_ids,
        status=SalonChainRequestStatus.PENDING,
    )
    db.add(request)
    await db.flush()

    # Инициатор голосует «за» своим салоном сразу (сам факт отправки запроса
    # уже согласие). Если все затронутые салоны принадлежат ЕМУ ЖЕ (например,
    # объединяет свои собственные две сети/салона) — остальные внешние
    # согласия не нужны, голосуем за всех и сразу исполняем.
    db.add(SalonChainVote(request_id=request.id, salon_id=from_salon.id,
                          approved=True, voted_by_user_id=initiator_user_id))

    if all(creators.get(sid) == initiator_user_id for sid in salon_ids):
        for sid in salon_ids:
            if sid != from_salon.id:
                db.add(SalonChainVote(request_id=request.id, salon_id=sid,
                                      approved=True, voted_by_user_id=initiator_user_id))
        await _execute_merge(db, request)
        request.status = SalonChainRequestStatus.ACCEPTED
        request.resolved_at = datetime.now(_tz.utc)

    await db.commit()
    await db.refresh(request)
    return request


async def cast_vote(db: AsyncSession, request: SalonChainRequest, salon_id: int, user_id: int, approved: bool) -> SalonChainRequest:
    if request.status != SalonChainRequestStatus.PENDING:
        raise SalonChainError("Запрос уже закрыт")
    if salon_id not in request.salon_ids:
        raise SalonChainError("Этот салон не участвует в запросе")

    existing = (await db.execute(
        select(SalonChainVote).where(SalonChainVote.request_id == request.id, SalonChainVote.salon_id == salon_id)
    )).scalar_one_or_none()
    if existing is not None:
        raise SalonChainError("От этого салона уже есть голос")

    db.add(SalonChainVote(request_id=request.id, salon_id=salon_id, approved=approved, voted_by_user_id=user_id))
    await db.flush()

    if not approved:
        request.status = SalonChainRequestStatus.REJECTED
        request.resolved_at = datetime.now(_tz.utc)
        await db.commit()
        await db.refresh(request)
        return request

    votes = (await db.execute(select(SalonChainVote).where(SalonChainVote.request_id == request.id))).scalars().all()
    approved_ids = {v.salon_id for v in votes if v.approved}
    if approved_ids >= set(request.salon_ids):
        await _execute_merge(db, request)
        request.status = SalonChainRequestStatus.ACCEPTED
        request.resolved_at = datetime.now(_tz.utc)

    await db.commit()
    await db.refresh(request)
    return request


async def cancel_request(db: AsyncSession, request: SalonChainRequest) -> None:
    if request.status != SalonChainRequestStatus.PENDING:
        raise SalonChainError("Запрос уже закрыт")
    request.status = SalonChainRequestStatus.CANCELLED
    request.resolved_at = datetime.now(_tz.utc)
    await db.commit()


async def leave_chain(db: AsyncSession, salon: Salon) -> None:
    """Покинуть сеть — односторонне, без согласия остальных участников."""
    old_chain_id = salon.chain_id
    if old_chain_id is None:
        raise SalonChainError("Салон не состоит в сети")

    # Состав сети сейчас меняется — активные запросы, где участвует этот салон
    # или его сеть, ссылаются на устаревший salon_ids. Отменяем их, чтобы
    # merge не ушёл по неверному составу.
    chain_member_ids = set((await db.execute(
        select(Salon.id).where(Salon.chain_id == old_chain_id)
    )).scalars().all())
    chain_member_ids.add(salon.id)
    for req in await _pending_requests_touching(db, chain_member_ids):
        req.status = SalonChainRequestStatus.CANCELLED
        req.resolved_at = datetime.now(_tz.utc)

    salon.chain_id = None
    await db.flush()

    remaining = (await db.execute(select(Salon).where(Salon.chain_id == old_chain_id))).scalars().all()
    if len(remaining) <= 1:
        # Сеть из одного салона не имеет смысла — распускаем её тоже.
        for s in remaining:
            s.chain_id = None
        chain = (await db.execute(select(SalonChain).where(SalonChain.id == old_chain_id))).scalar_one_or_none()
        if chain is not None:
            await db.delete(chain)
    await db.commit()


async def pending_requests_for_salon_ids(db: AsyncSession, salon_ids: list[int]) -> list[SalonChainRequest]:
    """Незакрытые запросы, где хотя бы один из salon_ids ещё не проголосовал
    (используется, чтобы показать владельцу «входящие» запросы на решение)."""
    if not salon_ids:
        return []
    all_pending = (await db.execute(
        select(SalonChainRequest).where(SalonChainRequest.status == SalonChainRequestStatus.PENDING)
    )).scalars().all()
    result = []
    for req in all_pending:
        if not (set(req.salon_ids) & set(salon_ids)):
            continue
        voted = {v.salon_id for v in (await db.execute(
            select(SalonChainVote).where(SalonChainVote.request_id == req.id)
        )).scalars().all()}
        if set(salon_ids) - voted:
            result.append(req)
    return result
