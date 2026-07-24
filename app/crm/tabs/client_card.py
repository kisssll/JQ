# app/crm/tabs/client_card.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.models import (
    Booking, BookingStatus, Review, ClientNote, User as UserModel,
    Master, Service as ServiceModel,
)
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.pages.business.utils import get_masters_data, get_master_ids
from app.services.loyalty_service import LoyaltyService


async def render_client_card(db: AsyncSession, salon, user, client_id: int) -> str:
    """Детальная карточка клиента: история визитов, отзывы, заметки салона."""

    client = (await db.execute(select(UserModel).where(UserModel.id == client_id))).scalar_one_or_none()
    if not client:
        return f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">{get_base_styles()}</head>
        <body>{render_header("business", user)}{render_sidebar("business")}
        <main style="margin-right:16rem;padding-top:3rem"><div class="section-container">
        <h1>Клиент не найден</h1><a href="/business/dashboard?salon_id={salon.id}" class="btn-outline">← Назад в панель</a>
        </div></main>{render_footer(user)}</body></html>"""

    masters, _ = await get_masters_data(db, salon.id)
    master_ids = get_master_ids(masters)
    master_names = {m.id: m for m in masters}

    bookings = []
    if master_ids:
        result = await db.execute(
            select(Booking, ServiceModel)
            .join(ServiceModel, ServiceModel.id == Booking.service_id)
            .where(Booking.client_id == client_id, Booking.master_id.in_(master_ids))
            .order_by(Booking.start_time.desc())
        )
        bookings = result.all()

    completed = [b for b, s in bookings if b.status == BookingStatus.COMPLETED]
    total_visits = len(completed)
    total_spent = sum(b.final_price or 0 for b in completed)
    first_visit = min((b.start_time for b in completed), default=None)
    last_visit = max((b.start_time for b in completed), default=None)

    async def master_user_name(master_id: int) -> str:
        m = master_names.get(master_id)
        if not m:
            return "—"
        mu = (await db.execute(select(UserModel).where(UserModel.id == m.user_id))).scalar_one_or_none()
        return mu.full_name if mu else "—"

    status_labels = {
        BookingStatus.PENDING: ("Ожидает", "#f59e0b"),
        BookingStatus.CONFIRMED: ("Подтверждена", "#3b82f6"),
        BookingStatus.COMPLETED: ("Завершена", "#22c55e"),
        BookingStatus.CANCELLED: ("Отменена", "#9ca3af"),
        BookingStatus.NO_SHOW: ("Неявка", "#ef4444"),
    }

    bookings_rows = ""
    for b, s in bookings:
        label, color = status_labels.get(b.status, (b.status.value, "#9ca3af"))
        price = f"{(b.final_price or s.price):,}".replace(",", " ")
        bookings_rows += f"""
        <tr>
            <td>{b.start_time.strftime('%d.%m.%Y %H:%M')}</td>
            <td>{s.name}</td>
            <td>{await master_user_name(b.master_id)}</td>
            <td><span style="color:{color};font-weight:600">{label}</span></td>
            <td>{price} ₽</td>
        </tr>"""

    reviews_result = await db.execute(
        select(Review).where(Review.client_id == client_id, Review.salon_id == salon.id).order_by(Review.created_at.desc())
    )
    reviews = reviews_result.scalars().all()
    reviews_html = "".join(
        f"""<div class="card" style="margin-bottom:0.75rem">
            <div style="color:#f59e0b">{'★' * r.rating}{'☆' * (5 - r.rating)}</div>
            <p style="margin-top:0.25rem">{r.comment or '<span class="text-muted">без комментария</span>'}</p>
            <p class="text-muted" style="font-size:0.75rem;margin-top:0.25rem">{r.created_at.strftime('%d.%m.%Y')}</p>
        </div>""" for r in reviews
    ) or '<p class="text-muted">Отзывов пока нет</p>'

    notes_result = await db.execute(
        select(ClientNote, UserModel)
        .join(UserModel, UserModel.id == ClientNote.author_id)
        .where(ClientNote.salon_id == salon.id, ClientNote.client_id == client_id)
        .order_by(ClientNote.created_at.desc())
    )
    notes = notes_result.all()
    notes_html = "".join(
        f"""<div class="card" style="margin-bottom:0.75rem">
            <p>{n.text}</p>
            <p class="text-muted" style="font-size:0.75rem;margin-top:0.5rem">{author.full_name or author.phone} · {n.created_at.strftime('%d.%m.%Y %H:%M')}</p>
        </div>""" for n, author in notes
    ) or '<p class="text-muted" id="no-notes">Заметок пока нет</p>'

    loyalty = await LoyaltyService.get_client_status(db, salon.id, client_id)

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{client.full_name or client.phone} — карточка клиента — руми</title>
    {get_base_styles()}
    <style>
        .analytics-kpi {{ display:flex; gap:1rem; margin-bottom:1.5rem; flex-wrap:wrap }}
        .kpi-card {{ background:var(--color-surface); border:1px solid var(--color-border); border-radius:1rem; padding:1.25rem 1.5rem; flex:1; min-width:150px }}
        .kpi-value {{ font-size:1.75rem; font-weight:700; color:var(--color-heading) }}
        .kpi-label {{ font-size:0.8rem; color:var(--color-muted) }}
        table {{ width:100%; border-collapse:collapse }}
        th {{ text-align:left; padding:0.75rem; border-bottom:2px solid var(--color-border); font-weight:600; color:var(--color-heading); white-space:nowrap }}
        td {{ padding:0.75rem; border-bottom:1px solid var(--color-border) }}
    </style>
</head>
<body>
    {render_header("business", user)}
    {render_sidebar("business")}

    <main style="margin-right:16rem;padding-top:2rem">
        <div class="section-container">
            <a href="/business/dashboard?salon_id={salon.id}" class="text-muted" style="font-size:0.875rem">← Назад в панель</a>
            <h1 class="text-display" style="font-size:2rem;margin:0.5rem 0 0.25rem">{client.full_name or 'Клиент'}</h1>
            <p class="text-muted" style="margin-bottom:1.5rem">{client.phone}</p>

            <div class="analytics-kpi">
                <div class="kpi-card"><div class="kpi-label">Визитов</div><div class="kpi-value">{total_visits}</div></div>
                <div class="kpi-card"><div class="kpi-label">Потрачено</div><div class="kpi-value" style="color:#22c55e">{f"{total_spent:,}".replace(",", " ")} ₽</div></div>
                <div class="kpi-card"><div class="kpi-label">Первый визит</div><div class="kpi-value" style="font-size:1.1rem">{first_visit.strftime('%d.%m.%Y') if first_visit else '—'}</div></div>
                <div class="kpi-card"><div class="kpi-label">Последний визит</div><div class="kpi-value" style="font-size:1.1rem">{last_visit.strftime('%d.%m.%Y') if last_visit else '—'}</div></div>
            </div>

            <div class="card" style="margin-bottom:1.5rem">
                <h3 style="margin-bottom:1rem">Лояльность в этом салоне</h3>
                <div class="grid-2" style="gap:1.5rem">
                    <div>
                        <label style="display:flex;align-items:center;gap:0.5rem;margin-bottom:1rem;cursor:pointer">
                            <input type="checkbox" id="loyaltyRegularCheckbox" {"checked" if loyalty["is_regular_client"] else ""}
                                   onchange="toggleRegularStatus(this.checked)">
                            Статус «постоянный клиент» (скидка {loyalty["regular_client_discount_percent"]}% в этом салоне)
                        </label>
                        <label style="display:block;font-weight:500;margin-bottom:0.5rem">Персональная скидка, %</label>
                        <div style="display:flex;gap:0.5rem">
                            <input type="number" id="personalDiscountInput" min="1" max="99"
                                   value="{loyalty["personal_discount_percent"] or ''}" placeholder="Не назначена"
                                   style="flex:1;padding:0.65rem;border:1px solid var(--color-border);border-radius:0.5rem">
                            <button type="button" class="btn-outline" style="font-size:0.8rem" onclick="savePersonalDiscount()">Сохранить</button>
                        </div>
                    </div>
                    <div>
                        <label style="display:block;font-weight:500;margin-bottom:0.5rem">Баллы: <strong id="bonusPointsValue">{loyalty["bonus_points"]}</strong></label>
                        <div style="display:flex;gap:0.5rem;margin-bottom:0.5rem">
                            <input type="number" id="pointsAmountInput" placeholder="+100 или -50" style="flex:1;padding:0.65rem;border:1px solid var(--color-border);border-radius:0.5rem">
                            <button type="button" class="btn-outline" style="font-size:0.8rem" onclick="adjustPoints()">Начислить/списать</button>
                        </div>
                        <input type="text" id="pointsCommentInput" placeholder="Причина (например: перенос из старой системы салона)"
                               style="width:100%;padding:0.65rem;border:1px solid var(--color-border);border-radius:0.5rem;font-size:0.85rem">
                    </div>
                </div>
            </div>

            <div class="card" style="overflow-x:auto;margin-bottom:1.5rem">
                <h3 style="margin-bottom:1rem">История записей</h3>
                <table>
                    <thead><tr><th>Дата</th><th>Услуга</th><th>Мастер</th><th>Статус</th><th>Сумма</th></tr></thead>
                    <tbody>{bookings_rows or '<tr><td colspan="5" style="text-align:center;padding:2rem;color:var(--color-muted)">Записей нет</td></tr>'}</tbody>
                </table>
            </div>

            <div class="grid-2">
                <div>
                    <h3 style="margin-bottom:1rem">Отзывы клиента</h3>
                    {reviews_html}
                </div>
                <div>
                    <h3 style="margin-bottom:1rem">Заметки</h3>
                    <form id="noteForm" style="display:flex;gap:0.5rem;margin-bottom:1rem">
                        <input id="noteText" type="text" placeholder="Например: аллергия на аммиак" required
                               style="flex:1;padding:0.65rem 0.85rem;border:1px solid var(--color-border);border-radius:0.5rem;font-size:0.875rem">
                        <button type="submit" class="btn-primary">Добавить</button>
                    </form>
                    <div id="notesList">{notes_html}</div>
                </div>
            </div>
        </div>
    </main>

    {render_footer(user)}

    <script>
        document.getElementById('noteForm').addEventListener('submit', async function(e) {{
            e.preventDefault();
            const input = document.getElementById('noteText');
            const text = input.value.trim();
            if (!text) return;
            try {{
                const res = await fetch('/api/v1/business/my-salon/clients/{client_id}/notes?salon_id={salon.id}', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ text: text }})
                }});
                if (res.ok) {{
                    location.reload();
                }} else {{
                    const data = await res.json().catch(() => ({{}}));
                    alert(data.detail || 'Не удалось сохранить заметку');
                }}
            }} catch (err) {{
                alert('Ошибка соединения с сервером');
            }}
        }});

        async function toggleRegularStatus(isRegular) {{
            const res = await fetch('/api/v1/loyalty/salon/{salon.id}/client/{client_id}/status', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ is_regular: isRegular }})
            }});
            if (!res.ok) {{
                const d = await res.json().catch(() => ({{}}));
                alert(d.detail || 'Не удалось изменить статус');
                document.getElementById('loyaltyRegularCheckbox').checked = !isRegular;
            }}
        }}

        async function savePersonalDiscount() {{
            const raw = document.getElementById('personalDiscountInput').value;
            const discount_percent = raw ? parseInt(raw) : null;
            const res = await fetch('/api/v1/loyalty/salon/{salon.id}/client/{client_id}/personal-discount', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ discount_percent }})
            }});
            if (res.ok) {{ alert('Сохранено'); }}
            else {{ const d = await res.json(); alert(d.detail || 'Ошибка'); }}
        }}

        async function adjustPoints() {{
            const amount = parseInt(document.getElementById('pointsAmountInput').value);
            const comment = document.getElementById('pointsCommentInput').value;
            if (!amount) {{ alert('Укажите сумму (например 100 или -50)'); return; }}
            const res = await fetch('/api/v1/loyalty/salon/{salon.id}/client/{client_id}/points', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ amount, comment }})
            }});
            if (res.ok) {{
                const d = await res.json();
                document.getElementById('bonusPointsValue').textContent = d.bonus_points;
                document.getElementById('pointsAmountInput').value = '';
                document.getElementById('pointsCommentInput').value = '';
            }} else {{
                const d = await res.json();
                alert(d.detail || 'Ошибка');
            }}
        }}
    </script>
</body>
</html>"""
