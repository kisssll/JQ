# app/crm/tabs/clients.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from app.models.models import Booking, BookingStatus, Service


async def render_crm_tab(db: AsyncSession, salon, masters, master_ids) -> str:
    """Вкладка CRM — клиенты салона."""
    
    clients_data = []
    if master_ids:
        bookings_result = await db.execute(
            select(Booking).where(
                Booking.master_id.in_(master_ids),
                Booking.status == BookingStatus.COMPLETED
            ).order_by(Booking.start_time.desc())
        )
        bookings = bookings_result.scalars().all()
        
        from app.models.models import User as UserModel
        clients_dict = {}
        for b in bookings:
            if b.client_id not in clients_dict:
                client = (await db.execute(select(UserModel).where(UserModel.id == b.client_id))).scalar_one_or_none()
                clients_dict[b.client_id] = {
                    "id": b.client_id,
                    "name": client.full_name if client else "Клиент",
                    "phone": client.phone if client else "—",
                    "visits": 0,
                    "total_spent": 0,
                    "last_visit": None
                }
            clients_dict[b.client_id]["visits"] += 1
            clients_dict[b.client_id]["total_spent"] += b.final_price or 0
            if not clients_dict[b.client_id]["last_visit"] or b.start_time > clients_dict[b.client_id]["last_visit"]:
                clients_dict[b.client_id]["last_visit"] = b.start_time
        
        clients_data = sorted(clients_dict.values(), key=lambda x: x["last_visit"] or datetime.min, reverse=True)
    
    total_clients = len(clients_data)
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = today.replace(day=1)
    
    new_this_month = 0
    for c in clients_data:
        if c["visits"] == 1 and c["last_visit"] and c["last_visit"] >= month_start:
            new_this_month += 1
    
    clients_rows = ""
    for c in clients_data[:50]:
        last_visit_str = c["last_visit"].strftime("%d.%m.%Y") if c["last_visit"] else "—"
        total_str = f"{c['total_spent']:,}".replace(",", " ")
        clients_rows += f"""
        <tr class="client-row" style="cursor:pointer" onclick="window.location.href='/business/clients/{c['id']}?salon_id={salon.id}'">
            <td><strong>{c['name']}</strong></td>
            <td>{c['phone']}</td>
            <td>{c['visits']}</td>
            <td><strong>{total_str} ₽</strong></td>
            <td>{last_visit_str}</td>
        </tr>"""
    
    return f"""
    <div id="tab-crm" class="tab-content">
        <div class="analytics-kpi">
            <div class="kpi-card">
                <div class="kpi-label">Всего клиентов</div>
                <div class="kpi-value">{total_clients}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Новых за месяц</div>
                <div class="kpi-value" style="color:var(--color-success)">{new_this_month}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Вернувшихся</div>
                <div class="kpi-value" style="color:var(--color-accent-text)">{total_clients - new_this_month}</div>
            </div>
        </div>
        
        <div class="card" style="overflow-x:auto">
            <table>
                <thead>
                    <tr><th>Клиент</th><th>Телефон</th><th>Визитов</th><th>Потрачено</th><th>Последний визит</th></tr>
                </thead>
                <tbody>
                    {clients_rows or '<tr><td colspan="5" style="text-align:center;padding:2rem;color:var(--color-muted)">Нет данных о клиентах</td></tr>'}
                </tbody>
            </table>
        </div>
    </div>"""