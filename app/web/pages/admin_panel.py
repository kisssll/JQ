# app/web/pages/admin_panel.py
"""Рендер админ-панели (/admin). Вкладки: обзор, пользователи, салоны, отзывы, аудит.
Самодостаточная страница в стиле проекта; действия постят на /api/v1/admin/*."""
import html
from datetime import datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    User, UserRole, Salon, SalonPhoto, Master, Service, Booking, Review, BookingStatus, AdminAudit,
    SalonModerationStatus, PhotoReport, PhotoReportStatus, ModelModerationStatus,
)
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.styles import get_base_styles
from app.web.components.icons import (
    ICON_ALERT_TRIANGLE,
    ICON_BUILDING2,
    ICON_CHART_COLUMN,
    ICON_CHECK,
    ICON_CIRCLE_CHECK,
    ICON_EYE,
    ICON_FILE_TEXT,
    ICON_FLAG,
    ICON_LOCK,
    ICON_MAP_PIN,
    ICON_MESSAGE_CIRCLE,
    ICON_MODEL,
    ICON_PHONE,
    ICON_SHIELD_CHECK,
    ICON_STAR_FILLED,
    ICON_TRASH,
    ICON_USERS,
    ICON_X,
)

ROLE_RU = {
    "client": "Клиент", "model": "Модель", "master": "Мастер",
    "business": "Бизнес", "admin": "Модератор",
}


def _esc(v) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def _badge(text, color):
    return f'<span style="display:inline-block;border-radius:2rem;padding:0.1rem 0.6rem;font-size:0.7rem;font-weight:700;color:#fff;background:{color}">{text}</span>'


def _active_badge(is_active):
    return _badge("активен", "#16a34a") if is_active else _badge("заблокирован", "#dc2626")


def _moderation_badge(status):
    m = {
        SalonModerationStatus.PENDING: ("на модерации", "#d97706"),
        SalonModerationStatus.APPROVED: ("одобрен", "#16a34a"),
        SalonModerationStatus.REJECTED: ("отклонён", "#dc2626"),
    }
    text, color = m.get(status, (str(status), "#6b7280"))
    return _badge(text, color)


# ── ВКЛАДКА: ЗАЯВКИ (модерация регистрации бизнеса) ──────────────────────────
def _applications_tab(pending, owner_phone_by_id, extra_by_id):
    """extra_by_id[salon.id] = {"photo": url|None, "services": [(name, price), ...]}"""
    cards = ""
    for s in pending:
        owner = owner_phone_by_id.get(s.creator_id, "—") if s.creator_id else "нет"
        submitted = s.created_at.strftime("%d.%m.%Y") if s.created_at else "—"
        extra = extra_by_id.get(s.id, {"photo": None, "services": []})

        photo_html = (
            f'<img src="{_esc(extra["photo"])}" loading="lazy" style="width:88px;height:88px;object-fit:cover;border-radius:0.75rem;flex-shrink:0">'
            if extra["photo"] else
            '<div style="width:88px;height:88px;border-radius:0.75rem;background:var(--color-border);'
            f'display:flex;align-items:center;justify-content:center;flex-shrink:0">{ICON_BUILDING2}</div>'
        )
        services = extra["services"]
        services_preview = ", ".join(f"{_esc(name)} ({price}₽)" for name, price in services[:3])
        if len(services) > 3:
            services_preview += f" и ещё {len(services) - 3}"
        services_line = services_preview or '<span class="text-muted">Услуги ещё не добавлены</span>'

        approve = (
            f'<form method="post" action="/api/v1/admin/salons/{s.id}/approve" style="display:inline">'
            f'<button class="btn-mini" style="border-color:#16a34a;color:#16a34a">{ICON_CHECK} Одобрить</button></form>'
        )
        reject = (
            f'<form method="post" action="/api/v1/admin/salons/{s.id}/reject" style="display:inline-flex;gap:0.25rem" '
            f'data-confirm="Отклонить заявку «{_esc(s.name)}»?" data-confirm-label="Подтвердить">'
            f'<input name="reason" placeholder="причина" '
            f'style="padding:0.3rem 0.5rem;border:1px solid var(--color-border);border-radius:0.4rem;width:140px">'
            f'<button class="btn-mini btn-danger">{ICON_X} Отклонить</button></form>'
        )

        cards += f"""
        <div class="card" style="display:flex;gap:1rem;padding:1rem;margin-bottom:0.75rem">
            {photo_html}
            <div style="flex:1;min-width:0">
                <div style="display:flex;justify-content:space-between;gap:1rem;flex-wrap:wrap">
                    <strong>{_esc(s.name)}</strong>
                    <span class="text-muted" style="font-size:0.8rem">подана {submitted}</span>
                </div>
                <p class="text-muted" style="font-size:0.85rem;margin:0.25rem 0">
                    {ICON_MAP_PIN} {_esc(s.address)} · {ICON_PHONE} {_esc(s.phone)} · владелец {_esc(owner)}
                </p>
                <p style="font-size:0.85rem;margin:0.25rem 0">{services_line}</p>
                <details style="margin:0.5rem 0">
                    <summary style="cursor:pointer;color:var(--color-primary);font-size:0.85rem">{ICON_EYE} Посмотреть подробнее</summary>
                    <div style="margin-top:0.5rem;font-size:0.85rem">
                        <p>{_esc(s.description) or '<span class="text-muted">Без описания</span>'}</p>
                        <p style="margin-top:0.4rem"><strong>Все услуги:</strong> {", ".join(f"{_esc(n)} ({p}₽)" for n, p in services) or "—"}</p>
                    </div>
                </details>
                <div style="margin-top:0.5rem">{approve} {reject}</div>
            </div>
        </div>"""
    if not cards:
        cards = '<p class="text-muted" style="padding:1.5rem;text-align:center">Новых заявок нет</p>'
    return f"""
    <div class="tab-content" id="tab-applications">
        <h2 style="margin-bottom:1rem">Заявки на регистрацию ({len(pending)})</h2>
        <p class="text-muted" style="margin-bottom:1rem;font-size:0.85rem">Салон работает только после одобрения: до этого он не виден в каталоге и запись закрыта.</p>
        {cards}
    </div>
    """


# ── ВКЛАДКА: АНКЕТЫ МОДЕЛЕЙ (модерация) ──────────────────────────────────────
def _model_applications_tab(pending_models):
    """pending_models — список User с is_model=True и model_moderation_status=PENDING."""
    cards = ""
    for u in pending_models:
        submitted = u.updated_at.strftime("%d.%m.%Y") if u.updated_at else "—"
        photo_html = (
            f'<img src="{_esc(u.model_photo_url)}" loading="lazy" style="width:88px;height:88px;object-fit:cover;border-radius:0.75rem;flex-shrink:0">'
            if u.model_photo_url else
            '<div style="width:88px;height:88px;border-radius:0.75rem;background:var(--color-border);'
            f'display:flex;align-items:center;justify-content:center;flex-shrink:0">{ICON_MODEL}</div>'
        )
        approve = (
            f'<form method="post" action="/api/v1/admin/models/{u.id}/approve" style="display:inline">'
            f'<button class="btn-mini" style="border-color:#16a34a;color:#16a34a">{ICON_CHECK} Одобрить</button></form>'
        )
        reject = (
            f'<form method="post" action="/api/v1/admin/models/{u.id}/reject" style="display:inline-flex;gap:0.25rem" '
            f'data-confirm="Отклонить анкету «{_esc(u.full_name or u.phone)}»?" data-confirm-label="Подтвердить">'
            f'<input name="reason" placeholder="причина" '
            f'style="padding:0.3rem 0.5rem;border:1px solid var(--color-border);border-radius:0.4rem;width:140px">'
            f'<button class="btn-mini btn-danger">{ICON_X} Отклонить</button></form>'
        )
        cards += f"""
        <div class="card" style="display:flex;gap:1rem;padding:1rem;margin-bottom:0.75rem">
            {photo_html}
            <div style="flex:1;min-width:0">
                <div style="display:flex;justify-content:space-between;gap:1rem;flex-wrap:wrap">
                    <strong>{_esc(u.full_name) or _esc(u.phone)}</strong>
                    <span class="text-muted" style="font-size:0.8rem">подана {submitted}</span>
                </div>
                <p class="text-muted" style="font-size:0.85rem;margin:0.25rem 0">{ICON_PHONE} {_esc(u.phone)}</p>
                <p style="font-size:0.85rem;margin:0.25rem 0">{_esc(u.model_bio) or '<span class="text-muted">Без описания</span>'}</p>
                {f'<p style="font-size:0.8rem;margin:0.25rem 0" class="text-muted">Ищет: {_esc(u.model_looking_for)}</p>' if u.model_looking_for else ''}
                <div style="margin-top:0.5rem">{approve} {reject}</div>
            </div>
        </div>"""
    if not cards:
        cards = '<p class="text-muted" style="padding:1.5rem;text-align:center">Новых анкет нет</p>'
    return f"""
    <div class="tab-content" id="tab-models">
        <h2 style="margin-bottom:1rem">Анкеты моделей на модерации ({len(pending_models)})</h2>
        <p class="text-muted" style="margin-bottom:1rem;font-size:0.85rem">Пока анкета не одобрена, салоны её не видят в кандидатах — как и с заявками салонов.</p>
        {cards}
    </div>
    """


# ── ВКЛАДКА: ОБЗОР ───────────────────────────────────────────────────────────
async def _overview(db, users):
    by_role = {}
    blocked = 0
    for u in users:
        by_role[u.role.value] = by_role.get(u.role.value, 0) + 1
        if not u.is_active:
            blocked += 1

    salons_total = (await db.execute(select(func.count(Salon.id)))).scalar() or 0
    salons_active = (await db.execute(select(func.count(Salon.id)).where(Salon.is_active == True))).scalar() or 0
    bookings_total = (await db.execute(select(func.count(Booking.id)))).scalar() or 0
    reviews_total = (await db.execute(select(func.count(Review.id)))).scalar() or 0

    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    b_today = (await db.execute(select(func.count(Booking.id)).where(Booking.start_time >= today))).scalar() or 0
    b_month = (await db.execute(select(func.count(Booking.id)).where(Booking.start_time >= month))).scalar() or 0
    revenue = (await db.execute(
        select(func.coalesce(func.sum(Booking.final_price), 0)).where(Booking.status == BookingStatus.COMPLETED)
    )).scalar() or 0

    def card(value, label):
        return f'<div class="stat-card"><div class="stat-value">{value}</div><div class="stat-label">{label}</div></div>'

    roles_cards = "".join(
        card(by_role.get(r, 0), ROLE_RU[r]) for r in ["client", "model", "master", "business", "admin"]
    )
    return f"""
    <div class="tab-content active" id="tab-overview">
        <h2 style="margin-bottom:1rem">Платформа</h2>
        <div class="stat-grid">
            {card(len(users), "Пользователей")}
            {card(blocked, "Заблокировано")}
            {card(f"{salons_active}/{salons_total}", "Салонов (актив/всего)")}
            {card(bookings_total, "Записей всего")}
            {card(b_today, "Записей сегодня")}
            {card(b_month, "Записей за месяц")}
            {card(f"{revenue:,}".replace(",", " ") + " ₽", "Выручка по завершённым")}
            {card(reviews_total, "Отзывов")}
        </div>
        <h3 style="margin:1.5rem 0 0.75rem">Пользователи по ролям</h3>
        <div class="stat-grid">{roles_cards}</div>
    </div>
    """


# ── ВКЛАДКА: ПОЛЬЗОВАТЕЛИ ────────────────────────────────────────────────────
def _users_tab(users, me_id):
    rows = ""
    for u in users:
        opts = "".join(
            f'<option value="{r}"{" selected" if u.role.value == r else ""}>{ROLE_RU[r]}</option>'
            for r in ["client", "model", "business", "admin"]
        )
        is_self = u.id == me_id
        role_form = (
            f'<form method="post" action="/api/v1/admin/users/{u.id}/role" style="display:inline-flex;gap:0.25rem">'
            f'<select name="role" class="custom-select" {"disabled" if is_self else ""}>{opts}</select>'
            f'<button class="btn-mini" {"disabled" if is_self else ""}>OK</button></form>'
            if u.role.value != "master" else '<span class="text-muted">мастер</span>'
        )
        toggle = (
            f'<form method="post" action="/api/v1/admin/users/{u.id}/toggle-active" style="display:inline">'
            f'<button class="btn-mini" {"disabled" if is_self else ""}>{"Разблок." if not u.is_active else "Блок."}</button></form>'
        )
        reset = (
            f'<form method="post" action="/api/v1/admin/users/{u.id}/reset-password" style="display:inline">'
            f'<button class="btn-mini">Сброс пароля</button></form>'
        )
        delete = (
            f'<form method="post" action="/api/v1/admin/users/{u.id}/delete" style="display:inline" '
            f'data-confirm="Удалить {_esc(u.phone)}?" data-confirm-label="Подтвердить">'
            f'<button class="btn-mini btn-danger" {"disabled" if is_self else ""}>Удалить</button></form>'
        )
        senior_toggle = ""
        if u.role.value == "admin":
            senior_toggle = (
                f'<form method="post" action="/api/v1/admin/users/{u.id}/toggle-senior" style="display:inline">'
                f'<button class="btn-mini" {"disabled" if is_self else ""}>'
                f'{"Снять старшинство" if u.is_senior_admin else "Сделать старшим"}</button></form>'
            )
        senior_badge = ' ' + _badge("старший", "#7c3aed") if u.role.value == "admin" and u.is_senior_admin else ""
        me_mark = ' <span class="text-muted">(вы)</span>' if is_self else ""
        rows += f"""<tr>
            <td>{u.id}</td>
            <td>{_esc(u.phone)}{me_mark}</td>
            <td>{_esc(u.full_name) or "—"}</td>
            <td>{role_form}{senior_badge}</td>
            <td>{_active_badge(u.is_active)}</td>
            <td style="white-space:nowrap">{toggle} {senior_toggle} {reset} {delete}</td>
        </tr>"""
    return f"""
    <div class="tab-content" id="tab-users">
        <h2 style="margin-bottom:1rem">Пользователи ({len(users)})</h2>
        <input id="userFilter" onkeyup="filterTable('userFilter','usersTable')" placeholder="Поиск по телефону/имени…"
               style="width:100%;max-width:360px;padding:0.5rem 0.75rem;border:1px solid var(--color-border);border-radius:0.5rem;margin-bottom:1rem">
        <div style="overflow-x:auto"><table id="usersTable">
            <thead><tr><th>ID</th><th>Телефон</th><th>Имя</th><th>Роль</th><th>Статус</th><th>Действия</th></tr></thead>
            <tbody>{rows}</tbody>
        </table></div>
    </div>
    """


# ── ВКЛАДКА: САЛОНЫ ──────────────────────────────────────────────────────────
def _salons_tab(salons, owner_phone_by_id):
    rows = ""
    for s in salons:
        owner = owner_phone_by_id.get(s.creator_id, "—") if s.creator_id else "нет"
        owner_form = (
            f'<form method="post" action="/api/v1/admin/salons/{s.id}/owner" style="display:inline-flex;gap:0.25rem">'
            f'<input name="owner_phone" placeholder="+7… (пусто = снять)" value="" '
            f'style="padding:0.3rem 0.5rem;border:1px solid var(--color-border);border-radius:0.4rem;width:150px">'
            f'<button class="btn-mini">Сменить</button></form>'
        )
        toggle = (
            f'<form method="post" action="/api/v1/admin/salons/{s.id}/toggle-active" style="display:inline">'
            f'<button class="btn-mini">{"Деактив." if s.is_active else "Активир."}</button></form>'
        )
        delete = (
            f'<form method="post" action="/api/v1/admin/salons/{s.id}/delete" style="display:inline" '
            f'data-confirm="Удалить салон «{_esc(s.name)}»?" data-confirm-label="Подтвердить">'
            f'<button class="btn-mini btn-danger">Удалить</button></form>'
        )
        rows += f"""<tr>
            <td>{s.id}</td>
            <td>{_esc(s.name)}</td>
            <td>{_esc(owner)}</td>
            <td>{ICON_STAR_FILLED} {s.rating} ({s.reviews_count})</td>
            <td>{_active_badge(s.is_active)} {_moderation_badge(s.moderation_status)}</td>
            <td>{_subscription_cell(s)}</td>
            <td style="white-space:nowrap">{owner_form} {toggle} {delete}<br>{_subscription_actions(s)}</td>
        </tr>"""
    return f"""
    <div class="tab-content" id="tab-salons">
        <h2 style="margin-bottom:1rem">Салоны ({len(salons)})</h2>
        <div style="overflow-x:auto"><table>
            <thead><tr><th>ID</th><th>Название</th><th>Владелец</th><th>Рейтинг</th><th>Статус</th><th>Подписка</th><th>Действия</th></tr></thead>
            <tbody>{rows}</tbody>
        </table></div>
    </div>
    """


# ── ВКЛАДКА: ЖАЛОБЫ НА ФОТО ──────────────────────────────────────────────────
def _reports_tab(reports):
    rows = ""
    for r in reports:
        thumb = (f'<a href="{_esc(r["url"])}" target="_blank"><img src="{_esc(r["url"])}" loading="lazy" '
                 f'style="width:64px;height:64px;object-fit:cover;border-radius:0.5rem"></a>') if r["url"] else "—"
        resolve = (
            f'<form method="post" action="/api/v1/admin/reports/{r["id"]}/resolve" style="display:inline" '
            f'data-confirm="Удалить фото и закрыть жалобу?" data-confirm-label="Подтвердить">'
            f'<button class="btn-mini btn-danger">{ICON_TRASH} Удалить фото</button></form>'
        )
        dismiss = (
            f'<form method="post" action="/api/v1/admin/reports/{r["id"]}/dismiss" style="display:inline">'
            f'<button class="btn-mini">Оставить</button></form>'
        )
        rows += f"""<tr>
            <td>{thumb}</td>
            <td>{_esc(r["salon"])}</td>
            <td>{_esc(r["reporter"])}</td>
            <td>{_esc(r["reason"]) or '<span class="text-muted">—</span>'}</td>
            <td style="white-space:nowrap">{resolve} {dismiss}</td>
        </tr>"""
    if not rows:
        rows = '<tr><td colspan="5" class="text-muted" style="padding:1.5rem;text-align:center">Открытых жалоб нет</td></tr>'
    return f"""
    <div class="tab-content" id="tab-reports">
        <h2 style="margin-bottom:1rem">Жалобы на фото ({len(reports)})</h2>
        <p class="text-muted" style="margin-bottom:1rem;font-size:0.85rem">«Удалить фото» — жалоба обоснована, фото убирается. «Оставить» — жалоба отклонена.</p>
        <div style="overflow-x:auto"><table>
            <thead><tr><th>Фото</th><th>Салон</th><th>Пожаловался</th><th>Причина</th><th>Действия</th></tr></thead>
            <tbody>{rows}</tbody>
        </table></div>
    </div>
    """


# ── ВКЛАДКА: ОТЗЫВЫ ──────────────────────────────────────────────────────────
def _subscription_cell(s) -> str:
    """Тариф, статус и срок доступа салона — в админке этого не было вовсе,
    и понять, платит ли салон, было неоткуда."""
    from datetime import datetime, timezone
    from app.services.tariffs import TARIFF_CATALOG

    tariff = TARIFF_CATALOG.get(getattr(s, "business_tier", None))
    plan = tariff.name if tariff else (getattr(s, "business_tier", None) or "—")
    status_labels = {
        "NONE": ("нет тарифа", "var(--color-muted)"),
        "TRIALING": ("пробный", "#f59e0b"),
        "ACTIVE": ("оплачен", "#22c55e"),
        "PAST_DUE": ("платёж не прошёл", "#ef4444"),
        "CANCELED": ("отменена", "var(--color-muted)"),
    }
    raw = getattr(s.subscription_status, "name", str(s.subscription_status))
    label, color = status_labels.get(raw, (raw, "var(--color-muted)"))

    until = getattr(s, "access_until", None)
    if until is None:
        until_str = '<span style="color:#ef4444">доступа нет</span>'
    else:
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        live = until > datetime.now(timezone.utc)
        until_str = (f'<span style="color:{"#22c55e" if live else "#ef4444"}">'
                     f'до {until.strftime("%d.%m.%Y")}{"" if live else " (истёк)"}</span>')

    pending = float(getattr(s, "pending_proration", 0) or 0)
    pending_str = (f'<br><span style="color:#f59e0b;font-size:0.75rem">доплата {int(round(pending))} ₽</span>'
                   if pending > 0 else "")
    return (f'<strong>{plan}</strong><br><span style="color:{color};font-size:0.8rem">{label}</span>'
            f'<br><span style="font-size:0.8rem">{until_str}</span>{pending_str}')


def _subscription_actions(s) -> str:
    """Ручное управление подпиской: продлить триал, выдать/продлить платный
    доступ, сменить тариф, снять доступ. Все действия — под старшим
    модератором и с записью в аудит (см. app/api/v1/endpoints/admin.py)."""
    from app.services.tariffs import TARIFF_CATALOG

    plan_options = "".join(
        f'<option value="{t.plan}">{t.name}</option>' for t in TARIFF_CATALOG.values()
    )
    return (
        f'<form method="post" action="/api/v1/admin/salons/{s.id}/grant-trial" style="display:inline">'
        f'<button class="btn-mini">+14 дн. триал</button></form> '
        f'<form method="post" action="/api/v1/admin/salons/{s.id}/grant-access" style="display:inline-flex;gap:0.25rem">'
        f'<input name="months" type="number" min="1" max="120" value="1" title="Месяцев доступа" '
        f'style="width:56px;padding:0.3rem;border:1px solid var(--color-border);border-radius:0.4rem">'
        f'<button class="btn-mini">Выдать доступ</button></form> '
        f'<form method="post" action="/api/v1/admin/salons/{s.id}/set-plan" style="display:inline-flex;gap:0.25rem">'
        f'<select name="plan" style="padding:0.3rem;border:1px solid var(--color-border);border-radius:0.4rem">{plan_options}</select>'
        f'<button class="btn-mini">Тариф</button></form> '
        f'<form method="post" action="/api/v1/admin/salons/{s.id}/revoke-access" style="display:inline" '
        f'data-confirm="Снять доступ у «{_esc(s.name)}»? Салон уйдёт из каталога." data-confirm-label="Снять">'
        f'<button class="btn-mini btn-danger">Снять доступ</button></form>'
    )


def _reviews_tab(reviews, client_by_id, master_name_by_id, salon_name_by_id):
    rows = ""
    for r in reviews:
        stars = ICON_STAR_FILLED * int(r.rating or 0)
        delete = (
            f'<form method="post" action="/api/v1/admin/reviews/{r.id}/delete" style="display:inline" '
            f'data-confirm="Удалить отзыв #{r.id}?" data-confirm-label="Подтвердить">'
            f'<button class="btn-mini btn-danger">Удалить</button></form>'
        )
        rows += f"""<tr>
            <td>{r.id}</td>
            <td>{_esc(client_by_id.get(r.client_id, "—"))}</td>
            <td>{_esc(master_name_by_id.get(r.master_id, "—"))}</td>
            <td>{_esc(salon_name_by_id.get(r.salon_id, "—"))}</td>
            <td>{stars}</td>
            <td>{_esc(r.comment) or "—"}</td>
            <td>{delete}</td>
        </tr>"""
    return f"""
    <div class="tab-content" id="tab-reviews">
        <h2 style="margin-bottom:1rem">Отзывы ({len(reviews)})</h2>
        <div style="overflow-x:auto"><table>
            <thead><tr><th>ID</th><th>Клиент</th><th>Мастер</th><th>Салон</th><th>Оценка</th><th>Комментарий</th><th></th></tr></thead>
            <tbody>{rows}</tbody>
        </table></div>
    </div>
    """


# ── ВКЛАДКА: АУДИТ ───────────────────────────────────────────────────────────
def _audit_tab(audits, actor_by_id):
    rows = ""
    for a in audits:
        when = a.created_at.strftime("%d.%m.%Y %H:%M") if a.created_at else ""
        rows += f"""<tr>
            <td style="white-space:nowrap">{when}</td>
            <td>{_esc(actor_by_id.get(a.actor_id, "#"+str(a.actor_id)))}</td>
            <td>{_esc(a.action)}</td>
            <td>{_esc(a.target_type)} #{a.target_id if a.target_id is not None else "—"}</td>
            <td>{_esc(a.detail)}</td>
        </tr>"""
    body = rows or '<tr><td colspan="5" class="text-muted">Пока нет записей</td></tr>'
    return f"""
    <div class="tab-content" id="tab-audit">
        <h2 style="margin-bottom:1rem">Аудит действий ({len(audits)})</h2>
        <div style="overflow-x:auto"><table>
            <thead><tr><th>Когда</th><th>Админ</th><th>Действие</th><th>Объект</th><th>Детали</th></tr></thead>
            <tbody>{body}</tbody>
        </table></div>
    </div>
    """


def _banner(q):
    ok = q.get("ok"); err = q.get("err")
    temp_pw = q.get("temp_pw"); temp_for = q.get("temp_for")
    out = ""
    if err:
        out += f'<div class="alert alert-err">{ICON_ALERT_TRIANGLE} {_esc(err)}</div>'
    if ok:
        out += f'<div class="alert alert-ok">{ICON_CIRCLE_CHECK} {_esc(ok)}</div>'
    if temp_pw:
        out += (f'<div class="alert alert-ok">{ICON_LOCK} Временный пароль для {_esc(temp_for)}: '
                f'<code style="font-weight:700">{_esc(temp_pw)}</code> — передайте пользователю, он виден один раз.</div>')
    return out


# ── СБОРКА СТРАНИЦЫ ──────────────────────────────────────────────────────────
async def render_admin_panel(db: AsyncSession, user, q) -> str:
    is_senior = user.is_senior_admin

    users = (await db.execute(select(User).order_by(User.role, User.id))).scalars().all()
    salons = (await db.execute(select(Salon).order_by(Salon.id))).scalars().all()
    masters = (await db.execute(select(Master))).scalars().all()

    phone_by_id = {u.id: u.phone for u in users}
    name_by_uid = {u.id: (u.full_name or u.phone) for u in users}
    salon_name_by_id = {s.id: s.name for s in salons}
    master_name_by_id = {m.id: name_by_uid.get(m.user_id, "Мастер") for m in masters}

    pending = [s for s in salons if s.moderation_status == SalonModerationStatus.PENDING]

    # Доп. данные для карточек заявок: фото + услуги (только по заявкам)
    extra_by_id = {}
    if pending:
        pending_ids = [s.id for s in pending]
        photo_rows = (await db.execute(
            select(SalonPhoto).where(SalonPhoto.salon_id.in_(pending_ids)).order_by(SalonPhoto.id)
        )).scalars().all()
        first_photo_by_salon = {}
        for p in photo_rows:
            first_photo_by_salon.setdefault(p.salon_id, p.url)

        services_rows = (await db.execute(
            select(Master.salon_id, Service.name, Service.price)
            .join(Service, Service.master_id == Master.id)
            .where(Master.salon_id.in_(pending_ids))
        )).all()
        services_by_salon: dict[int, list] = {}
        for salon_id, name, price in services_rows:
            services_by_salon.setdefault(salon_id, []).append((name, price))

        extra_by_id = {
            s.id: {"photo": first_photo_by_salon.get(s.id), "services": services_by_salon.get(s.id, [])}
            for s in pending
        }

    # Открытые жалобы на фото — доступны обоим уровням модерации
    from app.api.v1.endpoints.reports import _photo_and_salon_id
    pending_reports_raw = (await db.execute(
        select(PhotoReport).where(PhotoReport.status == PhotoReportStatus.PENDING).order_by(PhotoReport.id.desc())
    )).scalars().all()
    reports_data = []
    for rep in pending_reports_raw:
        url, sid = await _photo_and_salon_id(db, rep)
        reports_data.append({
            "id": rep.id, "url": url or "", "reason": rep.reason or "",
            "reporter": phone_by_id.get(rep.reporter_id, "—"),
            "salon": salon_name_by_id.get(sid, "—") if sid else "—",
        })

    applications_tab = _applications_tab(pending, phone_by_id, extra_by_id)
    reports_tab = _reports_tab(reports_data)

    pending_models = [
        u for u in users
        if u.is_model and u.model_moderation_status == ModelModerationStatus.PENDING
    ]
    model_applications_tab = _model_applications_tab(pending_models)

    # Вкладки «Пользователи/Салоны/Отзывы/Аудит/Обзор» — только старшему
    # модератору: базовый модератор видит и решает только заявки и жалобы.
    overview = users_tab = salons_tab = reviews_tab = audit_tab = ""
    if is_senior:
        reviews = (await db.execute(select(Review).order_by(Review.created_at.desc()).limit(200))).scalars().all()
        audits = (await db.execute(select(AdminAudit).order_by(AdminAudit.created_at.desc()).limit(100))).scalars().all()
        overview = await _overview(db, users)
        users_tab = _users_tab(users, user.id)
        salons_tab = _salons_tab(salons, phone_by_id)
        reviews_tab = _reviews_tab(reviews, phone_by_id, master_name_by_id, salon_name_by_id)
        audit_tab = _audit_tab(audits, phone_by_id)

    allowed_tabs = (
        {"overview", "users", "applications", "models", "reports", "salons", "reviews", "audit"}
        if is_senior else {"applications", "models", "reports"}
    )
    default_tab = "overview" if is_senior else "applications"
    _tab = q.get("tab", default_tab)
    active_tab = _tab if _tab in allowed_tabs else default_tab
    pending_badge = f' <span style="background:#d97706;color:#fff;border-radius:1rem;padding:0 0.4rem;font-size:0.7rem">{len(pending)}</span>' if pending else ""
    models_badge = f' <span style="background:#d97706;color:#fff;border-radius:1rem;padding:0 0.4rem;font-size:0.7rem">{len(pending_models)}</span>' if pending_models else ""
    reports_badge = f' <span style="background:#dc2626;color:#fff;border-radius:1rem;padding:0 0.4rem;font-size:0.7rem">{len(reports_data)}</span>' if reports_data else ""

    tab_nav = ""
    if is_senior:
        tab_nav += f'<button class="tab-btn" data-tab="overview" onclick="switchTab(\'overview\')">{ICON_CHART_COLUMN} Обзор</button>'
        tab_nav += f'<button class="tab-btn" data-tab="users" onclick="switchTab(\'users\')">{ICON_USERS} Пользователи</button>'
    tab_nav += f'<button class="tab-btn" data-tab="applications" onclick="switchTab(\'applications\')">{ICON_FILE_TEXT} Заявки{pending_badge}</button>'
    tab_nav += f'<button class="tab-btn" data-tab="models" onclick="switchTab(\'models\')">{ICON_MODEL} Модели{models_badge}</button>'
    tab_nav += f'<button class="tab-btn" data-tab="reports" onclick="switchTab(\'reports\')">{ICON_FLAG} Жалобы{reports_badge}</button>'
    if is_senior:
        tab_nav += f'<button class="tab-btn" data-tab="salons" onclick="switchTab(\'salons\')">{ICON_BUILDING2} Салоны</button>'
        tab_nav += f'<button class="tab-btn" data-tab="reviews" onclick="switchTab(\'reviews\')">{ICON_MESSAGE_CIRCLE} Отзывы</button>'
        tab_nav += f'<button class="tab-btn" data-tab="audit" onclick="switchTab(\'audit\')">{ICON_FILE_TEXT} Аудит</button>'

    role_label = "Старший модератор" if is_senior else "Модератор"

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Панель модератора — руми</title>
    {get_base_styles()}
    <style>
        /* Шапка position:fixed и занимает 60px — при padding-top:2rem заголовок
           страницы уезжал под плашку логотипа. */
        .admin-main {{ max-width:1280px; margin:0 auto; padding:5.5rem 1.5rem 2rem }}
        .tab-nav {{ display:flex; gap:0.25rem; border-bottom:1px solid var(--color-border); margin:1rem 0 1.5rem; flex-wrap:wrap }}
        /* Свои правила для .tab-btn убраны: общий вид вкладок задаёт бандл
           (.tab-btn/.tab-btn.active — пилюля с градиентом и белой подписью).
           Инлайновый <style> идёт после ссылки на бандл и при равной
           специфичности перебивал только color — активная вкладка получалась
           розовым текстом на розовом градиенте, контраст ~1,1:1. */
        .tab-btn svg {{ width:1.05rem; height:1.05rem; flex-shrink:0 }}
        .tab-btn {{ display:inline-flex; align-items:center; gap:0.4rem }}
        .tab-content {{ display:none }}
        .tab-content.active {{ display:block }}
        /* Флекс, а не grid c auto-fit: при восьми плитках и семи колонках
           последняя висела одна узкой сиротой во втором ряду. Здесь остаток
           растягивается по ширине и ряд выглядит законченным. */
        .stat-grid {{ display:flex; flex-wrap:wrap; gap:1rem }}
        .stat-grid > * {{ flex:1 1 calc(25% - 0.75rem); min-width:150px }}
        .stat-card {{ background:var(--color-surface); border:1px solid var(--color-border); border-radius:1rem; padding:1.25rem; text-align:center }}
        .stat-value {{ font-size:1.6rem; font-weight:700; color:var(--color-primary) }}
        .stat-label {{ font-size:0.8rem; color:var(--color-muted); margin-top:0.25rem }}
        table {{ width:100%; border-collapse:collapse; font-size:0.875rem }}
        th {{ text-align:left; padding:0.6rem; border-bottom:2px solid var(--color-border); font-weight:600; color:var(--color-heading); white-space:nowrap }}
        td {{ padding:0.6rem; border-bottom:1px solid var(--color-border); vertical-align:middle }}
        select, .btn-mini {{ font-size:0.8rem; padding:0.3rem 0.55rem; border:1px solid var(--color-border); border-radius:0.4rem; background:#fff; cursor:pointer }}
        .btn-mini:hover {{ border-color:var(--color-primary); color:var(--color-primary) }}
        .btn-mini:disabled {{ opacity:0.4; cursor:not-allowed }}
        .btn-danger:hover {{ border-color:#dc2626; color:#dc2626 }}
        .alert {{ padding:0.75rem 1rem; border-radius:0.5rem; margin-bottom:0.75rem; font-size:0.875rem }}
        .alert-ok {{ background:#dcfce7; color:#166534; border:1px solid #86efac }}
        .alert-err {{ background:#fee2e2; color:#991b1b; border:1px solid #fca5a5 }}
        .text-muted {{ color:var(--color-muted) }}
    </style>
</head>
<body>
    {render_header("admin")}
    <main class="admin-main">
        <h1 class="text-display" style="font-size:1.75rem">{ICON_SHIELD_CHECK} Панель модератора</h1>
        <p class="text-muted">{_esc(user.full_name or user.phone)} · {role_label}</p>
        {_banner(q)}
        <div class="tab-nav">
            {tab_nav}
        </div>
        {overview}
        {users_tab}
        {applications_tab}
        {model_applications_tab}
        {reports_tab}
        {salons_tab}
        {reviews_tab}
        {audit_tab}
    </main>
    {render_footer(user)}
    <script>
        function switchTab(name) {{
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.toggle('active', c.id === 'tab-' + name));
            history.replaceState(null, '', '/admin?tab=' + name);
        }}
        function filterTable(inputId, tableId) {{
            var q = document.getElementById(inputId).value.toLowerCase();
            document.querySelectorAll('#' + tableId + ' tbody tr').forEach(function(tr) {{
                tr.style.display = tr.textContent.toLowerCase().indexOf(q) > -1 ? '' : 'none';
            }});
        }}
        switchTab({active_tab!r});
    </script>
</body>
</html>"""
