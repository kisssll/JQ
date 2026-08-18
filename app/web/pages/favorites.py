# app/web/pages/favorites.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.models import Favorite, Salon, Master, User as UserModel
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.empty_state import render_empty_state
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.components.icons import (
    ICON_BUILDING_FAV,
    ICON_USER_FAV,
    ICON_STAR_FAV,
    ICON_TRASH_FAV,
    ICON_HEART_EMPTY,
)


async def render_favorites_page(db: AsyncSession, user) -> str:
    """Страница избранного — салоны и мастера с проверкой актуальности."""
    
    favorites_result = await db.execute(
        select(Favorite).where(Favorite.user_id == user.id).order_by(Favorite.created_at.desc())
    )
    favorites = favorites_result.scalars().all()
    
    salon_cards = ""
    master_cards = ""
    
    for fav in favorites:
        if fav.salon_id:
            salon = (await db.execute(select(Salon).where(Salon.id == fav.salon_id, Salon.is_active == True, Salon.is_hidden == False))).scalar_one_or_none()
            if salon:
                salon_cards += f"""
                <div class="fav-card">
                    <div class="fav-card-header">
                        <h3>{salon.name}</h3>
                        <span class="fav-rating">{ICON_STAR_FAV} {salon.rating} ({salon.reviews_count})</span>
                    </div>
                    <p style="color:var(--color-muted);font-size:0.9rem;margin-bottom:0.5rem">{salon.address or 'Адрес не указан'}</p>
                    <div style="display:flex;gap:0.5rem">
                        <a href="/salons/{salon.id}" class="btn-outline" style="font-size:0.8rem;padding:0.4rem 0.8rem">Перейти</a>
                        <button class="btn-outline fav-remove-btn" 
                                style="color:var(--color-muted);border-color:var(--color-border);font-size:0.8rem;padding:0.4rem 0.8rem"
                                data-type="salon" 
                                data-id="{salon.id}">
                            {ICON_TRASH_FAV} Убрать
                        </button>
                    </div>
                </div>"""
        
        elif fav.master_id:
            master = (await db.execute(select(Master).where(Master.id == fav.master_id, Master.is_active == True))).scalar_one_or_none()
            if master:
                master_user = (await db.execute(select(UserModel).where(UserModel.id == master.user_id))).scalar_one_or_none()
                master_name = master_user.full_name if master_user else "Мастер"
                salon = (await db.execute(select(Salon).where(Salon.id == master.salon_id, Salon.is_active == True))).scalar_one_or_none()
                salon_name = salon.name if salon else "Салон не указан"
                
                master_cards += f"""
                <div class="fav-card">
                    <div class="fav-card-header">
                        <h3>{master_name}</h3>
                        <span class="fav-rating">{ICON_STAR_FAV} {master.rating}</span>
                    </div>
                    <p style="color:var(--color-muted);font-size:0.9rem;margin-bottom:0.25rem">{master.specialization}</p>
                    <p style="color:var(--color-muted);font-size:0.85rem;margin-bottom:0.5rem">🏢 {salon_name}</p>
                    <div style="display:flex;gap:0.5rem">
                        <a href="/masters/{master.id}" class="btn-outline" style="font-size:0.8rem;padding:0.4rem 0.8rem">Перейти</a>
                        <button class="btn-outline fav-remove-btn" 
                                style="color:var(--color-muted);border-color:var(--color-border);font-size:0.8rem;padding:0.4rem 0.8rem"
                                data-type="master" 
                                data-id="{master.id}">
                            {ICON_TRASH_FAV} Убрать
                        </button>
                    </div>
                </div>"""
    
    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Избранное — руми</title>
    {get_base_styles()}
</head>
<body>
    {render_header("favorites")}
    {render_sidebar("favorites", user)}
    
    <main class="favorites-main">
        <div class="section-container">
            <h1 class="text-display favorites-title" style="font-size:2rem;margin-bottom:2rem">
                <span style="color:var(--color-primary);display:inline-flex;align-items:center;gap:0.3rem">
                    {ICON_HEART_EMPTY}
                </span> Избранное
            </h1>
            
            <!-- Салоны -->
            <h2 class="text-subtitle favorites-section-title" style="font-size:1.25rem;margin-bottom:1rem">
                <span class="fav-icon">{ICON_BUILDING_FAV}</span> Салоны
            </h2>
            {salon_cards or render_empty_state(title="Пока нет избранных салонов", text="Нажмите на сердечко в карточке салона, чтобы вернуться к нему позже.", icon=ICON_BUILDING_FAV, action_href="/salons", action_label="Найти салоны")}
            
            <!-- Мастера -->
            <h2 class="text-subtitle favorites-section-title" style="font-size:1.25rem;margin:2rem 0 1rem">
                <span class="fav-icon">{ICON_USER_FAV}</span> Мастера
            </h2>
            {master_cards or render_empty_state(title="Пока нет избранных мастеров", text="Сохраняйте мастеров, к которым хотите вернуться.", icon=ICON_USER_FAV, action_href="/salons", action_label="Найти мастеров")}
        </div>
        {render_footer(user)}
    </main>
</body>
</html>"""
    
    return html