# app/web/pages/master_detail.py
from app.web.components.escaping import e
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.models import Master, Service, User, MasterPhoto, Review, ReviewPhoto, ReviewTargetType
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.components.icons import (
    ICON_STAR_FILLED,
    ICON_X,
)


async def render_master_detail(db: AsyncSession, master_id: int, user=None) -> str:
    """Страница конкретного мастера."""
    
    result = await db.execute(select(Master).where(Master.id == master_id))
    master = result.scalar_one_or_none()
    
    if not master:
        return """<!DOCTYPE html><html><body style="text-align:center;padding:3rem"><h1>Мастер не найден</h1><a href="/">На главную</a></body></html>"""
    
    # Получаем пользователя (имя мастера)
    user_result = await db.execute(select(User).where(User.id == master.user_id))
    master_user = user_result.scalar_one_or_none()
    master_name = master_user.full_name if master_user else "Мастер"
    
    # Получаем услуги мастера
    services_result = await db.execute(
        select(Service).where(
            Service.master_id == master.id, Service.is_active == True, Service.is_model_practice == False,
        ).order_by(Service.price)
    )
    services = services_result.scalars().all()
    
    # Карточки услуг
    services_html = ""
    for srv in services:
        services_html += f"""
        <div style="display:flex;justify-content:space-between;align-items:center;padding:1rem;border-bottom:1px solid var(--color-border)">
            <div>
                <p style="font-weight:600">{e(srv.name)}</p>
                <p style="font-size:0.8rem;color:var(--color-muted)">{srv.duration_minutes} минут</p>
            </div>
            <div style="font-size:1.25rem;font-weight:700;color:var(--color-primary)">{srv.price} ₽</div>
        </div>
        """

    # ----- Портфолио: свои фото мастера + фото из отзывов про него -----
    is_own_page = bool(user and master_user and user.id == master_user.id)

    own_photos = (await db.execute(
        select(MasterPhoto).where(MasterPhoto.master_id == master.id).order_by(MasterPhoto.id.desc())
    )).scalars().all()

    review_photos_result = await db.execute(
        select(ReviewPhoto)
        .join(Review, Review.id == ReviewPhoto.review_id)
        .where(Review.master_id == master.id, Review.target_type == ReviewTargetType.MASTER)
        .order_by(ReviewPhoto.id.desc())
    )
    client_photos = review_photos_result.scalars().all()

    verified_count = (await db.execute(
        select(func.count(Review.id)).where(
            Review.master_id == master.id, Review.target_type == ReviewTargetType.MASTER, Review.is_verified == True,
        )
    )).scalar() or 0
    total_reviews_count = (await db.execute(
        select(func.count(Review.id)).where(Review.master_id == master.id, Review.target_type == ReviewTargetType.MASTER)
    )).scalar() or 0

    def _photo_tile(url: str, delete_url: str | None) -> str:
        delete_btn = (
            f'<button class="portfolio-photo-delete" data-url="{delete_url}" '
            f'style="position:absolute;top:0.25rem;right:0.25rem;border:none;border-radius:50%;'
            f'width:1.5rem;height:1.5rem;background:rgba(0,0,0,0.6);color:#fff;cursor:pointer">{ICON_X}</button>'
            if delete_url else ""
        )
        return (
            f'<div style="position:relative;display:inline-block">'
            f'<img src="{url}" alt="" loading="lazy" style="width:140px;height:140px;object-fit:cover;'
            f'border-radius:0.75rem;margin:0.25rem">{delete_btn}</div>'
        )

    own_photos_html = "".join(_photo_tile(p.url, f"/api/v1/upload/master/photo/{p.id}/delete" if is_own_page else None) for p in own_photos)
    client_photos_html = "".join(_photo_tile(p.url, None) for p in client_photos)

    upload_block = ""
    if is_own_page:
        upload_block = f"""
        <div style="margin:1rem 0">
            <input type="file" id="portfolioFileInput" accept="image/*" multiple style="display:none">
            <button class="btn-outline" onclick="document.getElementById('portfolioFileInput').click()">+ Добавить фото ({len(own_photos)}/20)</button>
        </div>
        <script>
            document.getElementById('portfolioFileInput').addEventListener('change', async (e) => {{
                const files = e.target.files;
                if (!files.length) return;
                const formData = new FormData();
                for (const f of files) formData.append('files', f);
                const res = await fetch('/api/v1/upload/master/photo', {{ method: 'POST', body: formData }});
                if (res.ok) {{ location.reload(); }}
                else {{ const d = await res.json().catch(() => ({{}})); alert(d.detail || 'Не удалось загрузить фото'); }}
            }});
            document.addEventListener('click', async (e) => {{
                if (e.target.classList.contains('portfolio-photo-delete')) {{
                    if (!confirm('Удалить это фото?')) return;
                    const res = await fetch(e.target.dataset.url, {{ method: 'POST' }});
                    if (res.ok) location.reload(); else alert('Не удалось удалить фото');
                }}
            }});
        </script>
        """

    portfolio_html = f"""
    <h2 style="margin:2rem 0 1rem">Портфолио</h2>
    {upload_block}
    <div class="card" style="padding:1.5rem">
        <h3 style="margin-bottom:0.5rem;font-size:1rem">Работы мастера</h3>
        <div style="display:flex;flex-wrap:wrap">
            {own_photos_html or '<p class="text-muted">Пока нет фото</p>'}
        </div>
        <h3 style="margin:1.5rem 0 0.5rem;font-size:1rem">Из отзывов клиентов</h3>
        <div style="display:flex;flex-wrap:wrap">
            {client_photos_html or '<p class="text-muted">Пока нет фото от клиентов</p>'}
        </div>
    </div>
    """
    
    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{e(master_name)} — {e(master.specialization)} — руми</title>
    {get_base_styles()}
</head>
<body>
    {render_header("salons")}
    {render_sidebar("salons", user)}
    
    <main style="margin-right: 16rem; padding-top: 2rem;">
        <div class="section-container">
            <a href="/salons/{master.salon_id}" style="color:var(--color-primary);text-decoration:none;margin-bottom:1rem;display:inline-block">← К салону</a>
            
            <div class="card" style="margin-bottom:2rem">
                <div style="display:flex;gap:2rem;align-items:center;margin-bottom:1.5rem">
                    <div style="width:8rem;height:8rem;border-radius:50%;background:linear-gradient(135deg,var(--color-primary),var(--color-accent));display:flex;align-items:center;justify-content:center;font-size:3rem;color:white">
                        {master_name[0]}
                    </div>
                    <div>
                        <h1 class="text-display" style="font-size:2rem">{e(master_name)}</h1>
                        <p style="font-size:1.1rem;color:var(--color-muted)">{e(master.specialization)}</p>
                        <p style="margin-top:0.5rem" title="{verified_count} из {total_reviews_count} отзывов подтверждены реальной записью">{ICON_STAR_FILLED} {master.rating} ({verified_count}/{total_reviews_count} подтверждено) · Опыт {master.experience_years} лет</p>
                        <form action="/api/v1/favorites/toggle-master/{master.id}" method="post" style="display:inline;margin-top:0.5rem">
                            <button type="submit" class="btn-outline" style="font-size:0.8rem;padding:0.4rem 0.8rem" title="Добавить мастера в избранное">{ICON_STAR_FILLED} В избранное</button>
                        </form>
                    </div>
                </div>
            </div>
            
            <h2 style="margin-bottom:1rem">Услуги и цены</h2>
            <div class="card">
                {services_html}
            </div>

            {portfolio_html}

            <div style="margin-top:2rem;text-align:center">
                <a href="/salons/{master.salon_id}" class="btn-primary" style="font-size:1rem;padding:1rem 2rem">Записаться</a>
            </div>
        </div>
        {render_footer(user)}
    </main>
</body>
</html>"""
    
    return html