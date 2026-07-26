# app/api/v1/endpoints/salon_chains.py
"""Сеть салонов: поиск партнёра, запрос на объединение, голосование
единогласным согласием создателей всех затронутых салонов, выход из сети.
См. app/services/salon_chain_service.py для самой логики слияния."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.models import Salon, SalonChainRequest, SalonModerationStatus, User
from app.api.deps import get_current_user, get_salon_membership
from app.services import salon_chain_service as chain_service

router = APIRouter()


async def _require_creator(db: AsyncSession, user: User, salon_id: int):
    membership = await get_salon_membership(db, user.id, salon_id)
    if membership is None or not membership.is_creator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Это решение о салоне может принять только его создатель",
        )
    return membership


async def _get_salon_or_404(db: AsyncSession, salon_id: int) -> Salon:
    salon = (await db.execute(select(Salon).where(Salon.id == salon_id))).scalar_one_or_none()
    if salon is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Салон не найден")
    return salon


async def _get_request_or_404(db: AsyncSession, request_id: int) -> SalonChainRequest:
    req = (await db.execute(select(SalonChainRequest).where(SalonChainRequest.id == request_id))).scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Запрос не найден")
    return req


@router.get("/search-salons")
async def search_salons(
    q: str,
    exclude_salon_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Поиск салона-партнёра по названию — для формы отправки запроса на
    объединение в сеть. Только опубликованные (не скрытые, не на модерации)
    салоны — предлагать объединение с чужой ещё не одобренной заявкой нет смысла."""
    q = q.strip()
    if len(q) < 2:
        return []
    rows = (await db.execute(
        select(Salon).where(
            Salon.name.ilike(f"%{q}%"),
            Salon.id != exclude_salon_id,
            Salon.is_active == True,  # noqa: E712
            Salon.is_hidden == False,  # noqa: E712
            Salon.moderation_status == SalonModerationStatus.APPROVED,
        ).order_by(Salon.name).limit(10)
    )).scalars().all()
    return [{"id": s.id, "name": s.name, "address": s.address} for s in rows]


class ChainRequestPayload(BaseModel):
    from_salon_id: int
    to_salon_id: int


@router.post("/request")
async def send_chain_request(
    payload: ChainRequestPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_creator(db, current_user, payload.from_salon_id)
    from_salon = await _get_salon_or_404(db, payload.from_salon_id)
    to_salon = await _get_salon_or_404(db, payload.to_salon_id)

    try:
        req = await chain_service.create_request(db, current_user.id, from_salon, to_salon)
    except chain_service.SalonChainError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    from app.services.notifications import notify_chain_request_created
    if req.status.value == "pending":
        await notify_chain_request_created(db, req)

    return {"status": req.status.value, "request_id": req.id}


class ChainVotePayload(BaseModel):
    salon_id: int
    approve: bool


@router.post("/request/{request_id}/vote")
async def vote_chain_request(
    request_id: int,
    payload: ChainVotePayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_creator(db, current_user, payload.salon_id)
    req = await _get_request_or_404(db, request_id)

    try:
        req = await chain_service.cast_vote(db, req, payload.salon_id, current_user.id, payload.approve)
    except chain_service.SalonChainError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    from app.services.notifications import notify_chain_request_resolved
    if req.status.value in ("accepted", "rejected"):
        await notify_chain_request_resolved(db, req)

    return {"status": req.status.value}


@router.post("/request/{request_id}/cancel")
async def cancel_chain_request(
    request_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    req = await _get_request_or_404(db, request_id)
    await _require_creator(db, current_user, req.from_salon_id)

    try:
        await chain_service.cancel_request(db, req)
    except chain_service.SalonChainError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"status": "cancelled"}


class ChainLeavePayload(BaseModel):
    salon_id: int


@router.post("/leave")
async def leave_chain(
    payload: ChainLeavePayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_creator(db, current_user, payload.salon_id)
    salon = await _get_salon_or_404(db, payload.salon_id)

    try:
        await chain_service.leave_chain(db, salon)
    except chain_service.SalonChainError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"status": "left"}
