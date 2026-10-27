# app/api/v1/endpoints/favorites.py
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.session import get_db
from app.services.live_accounts import live_master
from app.models.models import Favorite, Salon, Master

router = APIRouter()


async def _toggle(db: AsyncSession, user_id: int, *, salon_id=None, master_id=None) -> str:
    """Общий toggle. Возвращает 'added'|'removed'.

    Устойчив к историческим дублям (удаляет ВСЕ найденные строки, а не одну —
    scalar_one_or_none на дубле ронял запрос 500-кой) и к гонке двух
    параллельных запросов (уникальный индекс + IntegrityError = уже добавлено).
    """
    field = Favorite.salon_id == salon_id if salon_id else Favorite.master_id == master_id
    existing = (
        await db.execute(select(Favorite).where(Favorite.user_id == user_id, field))
    ).scalars().all()

    if existing:
        for row in existing:
            await db.delete(row)
        await db.commit()
        return "removed"

    db.add(Favorite(user_id=user_id, salon_id=salon_id, master_id=master_id))
    try:
        await db.commit()
    except IntegrityError:
        # Параллельный запрос успел вставить первым — считаем добавленным
        await db.rollback()
    return "added"


@router.post("/favorites/toggle-salon/{salon_id}")
async def toggle_favorite_salon(
    salon_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Добавить/убрать салон из избранного."""
    from app.web.auth import get_current_user_from_cookie
    
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    
    salon = (await db.execute(select(Salon).where(Salon.id == salon_id, Salon.is_active == True))).scalar_one_or_none()
    if not salon:
        return HTMLResponse(content="Салон не найден", status_code=404)

    result = await _toggle(db, user.id, salon_id=salon_id)
    return RedirectResponse(url=f"/favorites?{result}=1", status_code=302)


@router.post("/favorites/toggle-master/{master_id}")
async def toggle_favorite_master(
    master_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Добавить/убрать мастера из избранного."""
    from app.web.auth import get_current_user_from_cookie
    
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    
    master = (await db.execute(select(Master).where(Master.id == master_id, live_master()))).scalar_one_or_none()
    if not master:
        return HTMLResponse(content="Мастер не найден", status_code=404)

    result = await _toggle(db, user.id, master_id=master_id)
    return RedirectResponse(url=f"/favorites?{result}=1", status_code=302)


@router.get("/favorites/my")
async def get_my_favorites(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Возвращает списки id избранных салонов и мастеров."""
    from app.web.auth import get_current_user_from_cookie
    
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return {"salon_ids": [], "master_ids": []}
    
    favorites = (await db.execute(
        select(Favorite).where(Favorite.user_id == user.id)
    )).scalars().all()
    
    salon_ids = [f.salon_id for f in favorites if f.salon_id]
    master_ids = [f.master_id for f in favorites if f.master_id]
    
    return {"salon_ids": salon_ids, "master_ids": master_ids}