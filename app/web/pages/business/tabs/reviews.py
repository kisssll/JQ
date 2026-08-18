# app/web/pages/business/tabs/reviews.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.models import Master, User as UserModel, Review, ReviewPhoto, ReviewTargetType
from app.web.components.icons import (
    ICON_CIRCLE_CHECK,
    ICON_STAR_EMPTY,
    ICON_STAR_FILLED,
)

TARGET_LABELS = {
    ReviewTargetType.MASTER: "Мастер",
    ReviewTargetType.SALON: "Салон",
    ReviewTargetType.STAFF: "Сотрудник",
}


async def render_reviews_tab(db: AsyncSession, reviews, salon) -> str:
    """Вкладка Отзывы: список с тегами (тип цели/подтверждение), фото, фильтры.

    Жалобы на фото сюда намеренно не выводятся — их решает только
    платформенный модератор (см. app/api/v1/endpoints/reports.py), у салона
    был бы конфликт интересов при разборе жалобы на собственное фото."""
    reviews_rows = ""
    for r in reviews:
        client_result = await db.execute(select(UserModel).where(UserModel.id == r.client_id))
        client_user = client_result.scalar_one_or_none()
        client_name = client_user.full_name if client_user else "Клиент"

        target_name = "—"
        if r.target_type == ReviewTargetType.MASTER and r.master_id:
            master_result = await db.execute(select(Master).where(Master.id == r.master_id))
            master = master_result.scalar_one_or_none()
            if master:
                mu = (await db.execute(select(UserModel).where(UserModel.id == master.user_id))).scalar_one_or_none()
                target_name = mu.full_name if mu else "Мастер"
        elif r.target_type == ReviewTargetType.STAFF and r.staff_user_id:
            su = (await db.execute(select(UserModel).where(UserModel.id == r.staff_user_id))).scalar_one_or_none()
            target_name = su.full_name if su else "Сотрудник"
        else:
            target_name = "Салон в целом"

        stars = f"{ICON_STAR_FILLED}" * r.rating + f"{ICON_STAR_EMPTY}" * (5 - r.rating)
        date_str = r.created_at.strftime("%d.%m.%Y") if r.created_at else ""
        verified_html = (
            f'<span class="badge-tag" style="background:#dcfce7;color:#166534">{ICON_CIRCLE_CHECK} Подтверждено</span>'
            if r.is_verified else
            '<span class="badge-tag" style="background:#f3f4f6;color:var(--color-muted)">Без подтверждения</span>'
        )

        photos = (await db.execute(select(ReviewPhoto).where(ReviewPhoto.review_id == r.id))).scalars().all()
        photos_html = "".join(
            f'<img src="{p.url}" alt="" loading="lazy" style="width:48px;height:48px;object-fit:cover;'
            f'border-radius:0.4rem;margin-right:0.25rem">'
            for p in photos
        )

        reviews_rows += f"""
        <tr data-target-type="{r.target_type.value}" data-verified="{'1' if r.is_verified else '0'}">
            <td><strong>{client_name}</strong></td>
            <td>{TARGET_LABELS[r.target_type]}: {target_name}</td>
            <td>{verified_html}</td>
            <td>{stars}</td>
            <td style="max-width:260px">{r.comment or 'Без комментария'}</td>
            <td>{photos_html or '—'}</td>
            <td style="font-size:0.85rem;color:var(--color-muted)">{date_str}</td>
        </tr>"""

    return f"""
    <div id="tab-reviews" class="tab-content">
        <div class="card" style="margin-bottom:1.5rem">
            <div class="rating-summary">
                <div>
                    <div class="rating-big">{salon.rating}</div>
                    <div class="rating-stars">{"{ICON_STAR_FILLED}" * int(salon.rating)}{"{ICON_STAR_EMPTY}" * (5 - int(salon.rating))}</div>
                    <div style="font-size:0.85rem;color:var(--color-muted)">{salon.reviews_count} отзывов</div>
                </div>
            </div>
        </div>
        <div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-bottom:1rem">
            <button class="btn-outline reviews-filter-btn active" data-filter="all" onclick="reviewsTabFilter('all', this)">Все</button>
            <button class="btn-outline reviews-filter-btn" data-filter="master" onclick="reviewsTabFilter('master', this)">О мастерах</button>
            <button class="btn-outline reviews-filter-btn" data-filter="salon" onclick="reviewsTabFilter('salon', this)">О салоне</button>
            <button class="btn-outline reviews-filter-btn" data-filter="staff" onclick="reviewsTabFilter('staff', this)">О сотрудниках</button>
            <button class="btn-outline reviews-filter-btn" data-filter="verified" onclick="reviewsTabFilter('verified', this)">Только подтверждённые</button>
        </div>
        <div class="card" style="overflow-x:auto">
            <table>
                <thead>
                    <tr><th>Клиент</th><th>О чём</th><th>Статус</th><th>Оценка</th><th>Комментарий</th><th>Фото</th><th>Дата</th></tr>
                </thead>
                <tbody id="reviewsTabBody">
                    {reviews_rows or '<tr><td colspan="7" style="text-align:center;padding:2rem;color:var(--color-muted)">Пока нет отзывов</td></tr>'}
                </tbody>
            </table>
        </div>
        <script>
            function reviewsTabFilter(kind, btn) {{
                document.querySelectorAll('.reviews-filter-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                document.querySelectorAll('#reviewsTabBody tr[data-target-type]').forEach(el => {{
                    let show = true;
                    if (kind === 'verified') show = el.dataset.verified === '1';
                    else if (kind !== 'all') show = el.dataset.targetType === kind;
                    el.style.display = show ? '' : 'none';
                }});
            }}
        </script>
    </div>"""
