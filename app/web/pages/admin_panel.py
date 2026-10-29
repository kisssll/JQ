# app/web/pages/admin_panel.py
"""Рендер админ-панели (/admin). Вкладки: обзор, пользователи, салоны, отзывы, аудит.
Самодостаточная страница в стиле проекта; действия постят на /api/v1/admin/*."""
from app.web.components.escaping import e
import html
from datetime import datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.live_accounts import salon_has_live_owner

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


def _badge(text, tone):
    """Плашка состояния — общий компонент .r-status, тон: success/danger/warning/accent/neutral."""
    return f'<span class="r-status r-status--{tone}">{text}</span>'


def _btn(label, kind="secondary", disabled=False):
    """Кнопка действия в форме: .r-btn, а не вторая своя «мини-кнопка».

    kind: primary — главное действие, secondary — обычное, danger — разрушающее
    (контур, а не заливка: красной заливки в палитре нет)."""
    return f'<button class="r-btn r-btn--sm r-btn--{kind}"{" disabled" if disabled else ""}>{label}</button>'


def _count(n, tone):
    """Счётчик на вкладке: сколько ждёт решения."""
    return f' <span class="adm-count adm-count--{tone}">{n}</span>' if n else ""


def _active_badge(is_active):
    return _badge("активен", "success") if is_active else _badge("заблокирован", "danger")


def _deleted_badge():
    return _badge("удален", "neutral")


def _user_status(u, master, self_deleted: set) -> str:
    """Статус человека и, если он мастер, его карточки — одной картиной.

    До решения 0016 у отключённого человека карточка числилась «активной»:
    флаг карточки жил отдельно от флага аккаунта. Теперь карточка считается
    принимающей, только когда живы оба, — ровно по тому же правилу, по
    которому её показывает каталог (app/services/live_accounts.py).
    """
    if u.is_active:
        badge = _active_badge(True)
    elif u.id in self_deleted:
        badge = _badge("удалил аккаунт", "danger")
    else:
        badge = _active_badge(False)
    if master is None:
        return f'<div class="adm-badges">{badge}</div>'
    if u.is_active and master.is_active:
        card = _badge("карточка: принимает", "success")
    else:
        card = _badge("карточка: не принимает", "neutral")
    return f'<div class="adm-badges">{badge}{card}</div>'


def _moderation_badge(status):
    m = {
        SalonModerationStatus.PENDING: ("на модерации", "warning"),
        SalonModerationStatus.APPROVED: ("одобрен", "success"),
        SalonModerationStatus.REJECTED: ("отклонён", "danger"),
    }
    text, color = m.get(status, (str(status), "neutral"))
    return _badge(text, color)


def _thumb(url, size, icon=""):
    """Квадратик с фото или заглушкой-иконкой. Размер — классом, не style=."""
    if url:
        return f'<img class="adm-thumb adm-thumb--{size}" src="{_esc(url)}" loading="lazy" alt="">'
    return f'<div class="adm-thumb adm-thumb--{size} adm-thumb--empty">{icon}</div>'


def _reject_form(action, confirm, label=f"{ICON_X} Отклонить"):
    """Отклонение с причиной. Разрушающее, поэтому в группе .adm-danger и с подтверждением."""
    return (
        f'<div class="adm-danger adm-danger--inline">'
        f'<form method="post" action="{action}" class="adm-form" '
        f'data-confirm="{confirm}" data-confirm-label="Подтвердить">'
        f'<input name="reason" placeholder="причина" aria-label="Причина отказа" class="r-input adm-input adm-input--reason">'
        f'{_btn(label, "danger")}</form></div>'
    )


# ── ВКЛАДКА: ЗАЯВКИ (модерация регистрации бизнеса) ──────────────────────────
def _applications_tab(pending, owner_phone_by_id, extra_by_id):
    """extra_by_id[salon.id] = {"photo": url|None, "services": [(name, price), ...]}"""
    cards = ""
    for s in pending:
        owner = owner_phone_by_id.get(s.creator_id, "—") if s.creator_id else "нет"
        submitted = s.created_at.strftime("%d.%m.%Y") if s.created_at else "—"
        extra = extra_by_id.get(s.id, {"photo": None, "services": []})

        photo_html = _thumb(extra["photo"], "lg", ICON_BUILDING2)
        services = extra["services"]
        services_preview = ", ".join(f"{_esc(name)} ({price}₽)" for name, price in services[:3])
        if len(services) > 3:
            services_preview += f" и ещё {len(services) - 3}"
        services_line = services_preview or '<span class="text-muted">Услуги ещё не добавлены</span>'

        approve = (
            f'<form method="post" action="/api/v1/admin/salons/{s.id}/approve" class="adm-form">'
            f'{_btn(f"{ICON_CHECK} Одобрить", "primary")}</form>'
        )
        reject = _reject_form(
            f"/api/v1/admin/salons/{s.id}/reject", f"Отклонить заявку «{_esc(s.name)}»?"
        )

        cards += f"""
        <article class="r-card adm-app">
            {photo_html}
            <div class="adm-app__body">
                <div class="adm-app__head">
                    <strong>{_esc(s.name)}</strong>
                    <span class="adm-small text-muted">подана {submitted}</span>
                </div>
                <p class="adm-meta text-muted">
                    {ICON_MAP_PIN} {_esc(s.address)} · {ICON_PHONE} {_esc(s.phone)} · владелец {_esc(owner)}
                </p>
                <p class="adm-text">{services_line}</p>
                <details class="adm-details">
                    <summary>{ICON_EYE} Посмотреть подробнее</summary>
                    <div class="adm-details__body">
                        <p>{_esc(s.description) or '<span class="text-muted">Без описания</span>'}</p>
                        <p><strong>Все услуги:</strong> {", ".join(f"{_esc(n)} ({p}₽)" for n, p in services) or "—"}</p>
                    </div>
                </details>
                <div class="adm-actions">{approve}{reject}</div>
            </div>
        </article>"""
    if not cards:
        cards = '<p class="adm-empty">Новых заявок нет</p>'
    return f"""
    <div class="tab-content" id="tab-applications">
        <h2 class="adm-tab-title">Заявки на регистрацию ({len(pending)})</h2>
        <p class="adm-lead">Салон работает только после одобрения: до этого он не виден в каталоге и запись закрыта.</p>
        <div class="adm-list">{cards}</div>
    </div>
    """


# ── ВКЛАДКА: АНКЕТЫ МОДЕЛЕЙ (модерация) ──────────────────────────────────────
def _model_applications_tab(pending_models):
    """pending_models — список User с is_model=True и model_moderation_status=PENDING."""
    cards = ""
    for u in pending_models:
        submitted = u.updated_at.strftime("%d.%m.%Y") if u.updated_at else "—"
        photo_html = _thumb(u.model_photo_url, "lg", ICON_MODEL)
        approve = (
            f'<form method="post" action="/api/v1/admin/models/{u.id}/approve" class="adm-form">'
            f'{_btn(f"{ICON_CHECK} Одобрить", "primary")}</form>'
        )
        reject = _reject_form(
            f"/api/v1/admin/models/{u.id}/reject",
            f"Отклонить анкету «{_esc(u.full_name or u.phone)}»?",
        )
        looking = (f'<p class="adm-small text-muted">Ищет: {_esc(u.model_looking_for)}</p>'
                   if u.model_looking_for else '')
        cards += f"""
        <article class="r-card adm-app">
            {photo_html}
            <div class="adm-app__body">
                <div class="adm-app__head">
                    <strong>{_esc(u.full_name) or _esc(u.phone)}</strong>
                    <span class="adm-small text-muted">подана {submitted}</span>
                </div>
                <p class="adm-meta text-muted">{ICON_PHONE} {_esc(u.phone)}</p>
                <p class="adm-text">{_esc(u.model_bio) or '<span class="text-muted">Без описания</span>'}</p>
                {looking}
                <div class="adm-actions">{approve}{reject}</div>
            </div>
        </article>"""
    if not cards:
        cards = '<p class="adm-empty">Новых анкет нет</p>'
    return f"""
    <div class="tab-content" id="tab-models">
        <h2 class="adm-tab-title">Анкеты моделей на модерации ({len(pending_models)})</h2>
        <p class="adm-lead">Пока анкета не одобрена, салоны её не видят в кандидатах — как и с заявками салонов.</p>
        <div class="adm-list">{cards}</div>
    </div>
    """


# ── ВКЛАДКА: ОБЗОР ───────────────────────────────────────────────────────────
async def _overview(db, users, salons_active=None):
    by_role = {}
    blocked = 0
    for u in users:
        by_role[u.role.value] = by_role.get(u.role.value, 0) + 1
        if not u.is_active:
            blocked += 1

    salons_total = (await db.execute(select(func.count(Salon.id)))).scalar() or 0
    if salons_active is None:
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
        return f'<div class="adm-stat"><div class="adm-stat__value">{value}</div><div class="adm-stat__label">{label}</div></div>'

    roles_cards = "".join(
        card(by_role.get(r, 0), ROLE_RU[r]) for r in ["client", "model", "master", "business", "admin"]
    )
    return f"""
    <div class="tab-content active" id="tab-overview">
        <h2 class="adm-tab-title">Платформа</h2>
        <div class="adm-stats">
            {card(len(users), "Пользователей")}
            {card(blocked, "Заблокировано")}
            {card(f"{salons_active}/{salons_total}", "Салонов (актив/всего)")}
            {card(bookings_total, "Записей всего")}
            {card(b_today, "Записей сегодня")}
            {card(b_month, "Записей за месяц")}
            {card(f"{revenue:,}".replace(",", " ") + " ₽", "Выручка по завершённым")}
            {card(reviews_total, "Отзывов")}
        </div>
        <h3 class="adm-section-title">Пользователи по ролям</h3>
        <div class="adm-stats">{roles_cards}</div>
    </div>
    """


# ── ВКЛАДКА: ПОЛЬЗОВАТЕЛИ ────────────────────────────────────────────────────
def _users_tab(users, me_id, master_by_uid=None, self_deleted=None):
    master_by_uid = master_by_uid or {}
    self_deleted = self_deleted or set()
    rows = ""
    for u in users:
        opts = "".join(
            f'<option value="{r}"{" selected" if u.role.value == r else ""}>{ROLE_RU[r]}</option>'
            for r in ["client", "model", "business", "admin"]
        )
        is_self = u.id == me_id
        role_form = (
            f'<form method="post" action="/api/v1/admin/users/{u.id}/role" class="adm-form adm-form--role">'
            f'<select name="role" class="r-input adm-input adm-select" aria-label="Роль" {"disabled" if is_self else ""}>{opts}</select>'
            f'{_btn("OK", disabled=is_self)}</form>'
            if u.role.value != "master" else '<span class="text-muted">мастер</span>'
        )
        # Блокировка разрушающая, а разблокировка — нет: подтверждение только на первую.
        block_confirm = (
            f' data-confirm="Заблокировать {_esc(u.phone)}? Войти он больше не сможет." '
            f'data-confirm-label="Заблокировать"' if u.is_active else ""
        )
        toggle = (
            f'<form method="post" action="/api/v1/admin/users/{u.id}/toggle-active" class="adm-form"{block_confirm}>'
            f'{_btn("Блок." if u.is_active else "Разблок.", "danger" if u.is_active else "secondary", is_self)}</form>'
        )
        trial_form = ""
        if u.is_model:
            trial_form = (
                f'<form method="post" action="/api/v1/admin/users/{u.id}/grant-trial" class="adm-form">'
                f'<label class="adm-field"><span class="adm-field-label">Дней</span>'
                f'<input name="days" type="number" min="1" max="365" value="30" class="r-input adm-input is-num"></label>'
                f'{_btn("+trial")}</form>'
            )
        reset = (
            f'<form method="post" action="/api/v1/admin/users/{u.id}/reset-password" class="adm-form" '
            f'data-confirm="Сбросить пароль у {_esc(u.phone)}? Старый пароль перестанет работать." '
            f'data-confirm-label="Сбросить">'
            f'{_btn("Сброс пароля", "danger")}</form>'
        )
        delete = (
            f'<form method="post" action="/api/v1/admin/users/{u.id}/delete" class="adm-form" '
            f'data-confirm="Удалить {_esc(u.phone)}?" data-confirm-label="Подтвердить">'
            f'{_btn("Удалить", "danger", is_self)}</form>'
        )
        senior_toggle = ""
        if u.role.value == "admin":
            senior_toggle = (
                f'<form method="post" action="/api/v1/admin/users/{u.id}/toggle-senior" class="adm-form">'
                f'{_btn("Снять старшинство" if u.is_senior_admin else "Сделать старшим", disabled=is_self)}</form>'
            )
        senior_badge = _badge("старший", "accent") if u.role.value == "admin" and u.is_senior_admin else ""
        me_mark = ' <span class="text-muted">(вы)</span>' if is_self else ""
        main_actions = (f'<div class="adm-actions">{trial_form}{senior_toggle}</div>'
                        if trial_form or senior_toggle else "")
        rows += f"""<tr>
            <td class="adm-num">{u.id}</td>
            <td class="adm-nowrap">{_esc(u.phone)}{me_mark}</td>
            <td>{_esc(u.full_name) or "—"}</td>
            <td><div class="adm-stack">{role_form}{senior_badge}</div></td>
            <td>{_user_status(u, master_by_uid.get(u.id), self_deleted)}</td>
            <td>
                <div class="adm-stack">
                    {main_actions}
                    <div class="adm-danger adm-danger--inline">{toggle}{reset}{delete}</div>
                </div>
            </td>
        </tr>"""
    return f"""
    <div class="tab-content" id="tab-users">
        <h2 class="adm-tab-title">Пользователи ({len(users)})</h2>
        <div class="adm-toolbar">
            <input id="userFilter" type="search" class="r-input adm-search" oninput="filterTable('userFilter','usersTable')"
                   placeholder="Поиск по телефону или имени…" aria-label="Поиск пользователя">
        </div>
        <div class="adm-table-wrap"><table id="usersTable" class="adm-table adm-table--users">
            <thead><tr><th class="adm-col-id">ID</th><th class="adm-col-phone">Телефон</th><th class="adm-col-name">Имя</th><th class="adm-col-role">Роль</th><th class="adm-col-status">Статус</th><th>Действия</th></tr></thead>
            <tbody>{rows}</tbody>
        </table></div>
    </div>
    """


# ── ВКЛАДКА: САЛОНЫ ──────────────────────────────────────────────────────────
def _now_utc():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def _salons_tab(salons, owner_phone_by_id, live_salon_ids=None):
    """Салон = карточка, а не строка таблицы.

    В строке жили десять контролов в одной ячейке на 620px, разделённые голым
    <br>: два поля без подписей, системный <select> и кнопки-обрубки
    «Деактив.», «Активир.», «Тариф» — понять, что делает каждая, было нельзя,
    а таблица уезжала вбок. Карточка даёт место на подписи и раскладывает
    действия по сетке: владелец и состояние сверху, подписка во всю ширину,
    разрушающее — отдельной группой внизу (решение 0018, п. 3).
    """
    from app.services.tariffs import TARIFF_CATALOG

    # None — значит не посчитали (старые вызовы): считаем все салоны живыми.
    live_ids = live_salon_ids if live_salon_ids is not None else {s.id for s in salons}

    plan_options = "".join(
        f'<option value="{t.plan}">{e(t.name)}</option>' for t in TARIFF_CATALOG.values()
    )

    def render_cards(group):
        cards = ""
        for s in group:
            owner = owner_phone_by_id.get(s.creator_id, "—") if s.creator_id else "нет"
            toggle_label = "Деактивировать" if s.is_active else "Активировать"
            winner_until = getattr(s, "contest_winner_until", None)
            is_winner = bool(winner_until and winner_until > _now_utc())
            # Приз конечный: метка и подъём живут до contest_winner_until.
            if is_winner:
                winner_action = (
                    f'<form method="post" action="/api/v1/admin/salons/{s.id}/contest-winner" class="adm-form" '
                    f'data-confirm="Снять с «{_esc(s.name)}» отметку победителя конкурса?" '
                    f'data-confirm-label="Снять">'
                    f'<input type="hidden" name="months" value="0">'
                    f'{_btn(f"Снять победителя (до {winner_until:%d.%m.%Y})")}'
                    f'</form>'
                )
            else:
                winner_action = (
                    f'<form method="post" action="/api/v1/admin/salons/{s.id}/contest-winner" class="adm-form" '
                    f'data-confirm="Отметить «{_esc(s.name)}» победителем конкурса на 3 месяца?" '
                    f'data-confirm-label="Отметить">'
                    f'<input type="hidden" name="months" value="3">'
                    f'{_btn("Победитель конкурса")}'
                    f'</form>'
                )
            if s.is_deleted:
                status_badges = _deleted_badge()
            elif s.is_active and s.id not in live_ids:
                # Флаг салона «активен», но владелец отключён — в каталоге
                # и записи салона нет, и админка не должна говорить обратное.
                status_badges = _badge("владелец отключён", "danger")
            else:
                status_badges = _active_badge(s.is_active)
            salon_action = (
                f'''<form method="post" action="/api/v1/admin/salons/{s.id}/restore" class="adm-form"
                    data-confirm="Восстановить салон «{_esc(s.name)}»?" data-confirm-label="Восстановить">
                    {_btn("Восстановить")}
                </form>'''
                if s.is_deleted else
                f'''<form method="post" action="/api/v1/admin/salons/{s.id}/toggle-active" class="adm-form"
                    data-confirm="{toggle_label} салон «{_esc(s.name)}»?" data-confirm-label="{toggle_label}">
                    {_btn(toggle_label)}
                </form>'''
            )
            # Удалённый салон уже удалён: второй раз «Удалить» ему не предлагаем,
            # а «Снять доступ» остаётся (как и было).
            delete_form = "" if s.is_deleted else (
                f'''<form method="post" action="/api/v1/admin/salons/{s.id}/delete" class="adm-form"
                    data-confirm="Удалить салон «{_esc(s.name)}»?" data-confirm-label="Удалить">
                    {_btn("Удалить салон", "danger")}
                </form>'''
            )

            cards += f"""
        <article class="r-card adm-salon">
            <header class="adm-salon-head">
                <div class="adm-salon-title">
                    <strong>{_esc(s.name)}</strong>
                    <span class="adm-salon-id">#{s.id}</span>
                </div>
                <div class="adm-salon-badges">
                    {status_badges}{_moderation_badge(s.moderation_status)}
                </div>
            </header>

            <div class="adm-salon-facts">
                <span>Владелец: <strong>{_esc(owner)}</strong></span>
                <span>{ICON_STAR_FILLED} {s.rating} ({s.reviews_count})</span>
                {_subscription_cell(s)}
            </div>

            <div class="adm-salon-grid">
                <section class="adm-group">
                    <h4 class="adm-group-title">Владелец</h4>
                    <form method="post" action="/api/v1/admin/salons/{s.id}/owner" class="adm-form">
                        <label class="adm-field">
                            <span class="adm-field-label">Новый владелец</span>
                            <input name="owner_phone" placeholder="+7 999 123-45-67" value=""
                                   class="r-input adm-input" aria-label="Телефон нового владельца">
                        </label>
                        {_btn("Назначить")}
                    </form>
                    <p class="adm-hint">Пустое поле снимает владельца</p>
                </section>

                <section class="adm-group">
                    <h4 class="adm-group-title">Состояние и конкурс</h4>
                    <div class="adm-actions">
                        {salon_action}
                        {winner_action}
                    </div>
                </section>

                <section class="adm-group adm-group--wide">
                    <h4 class="adm-group-title">Подписка</h4>
                    <div class="adm-forms">
                        <form method="post" action="/api/v1/admin/salons/{s.id}/grant-trial" class="adm-form">
                            <label class="adm-field">
                                <span class="adm-field-label">Дней</span>
                                <input name="days" type="number" min="1" max="365" value="30"
                                       class="r-input adm-input is-num" aria-label="Сколько дней бесплатного периода выдать">
                            </label>
                            {_btn("Дать бесплатно")}
                        </form>
                        <div class="adm-form-pair">
                            <form method="post" action="/api/v1/admin/salons/{s.id}/grant-access" class="adm-form">
                                <label class="adm-field">
                                    <span class="adm-field-label">Месяцев</span>
                                    <input name="months" type="number" min="1" max="120" value="1"
                                           class="r-input adm-input is-num" aria-label="Сколько месяцев доступа выдать">
                                </label>
                                {_btn("Выдать доступ")}
                            </form>
                            <!-- Отдельной формой, а не второй кнопкой в соседней: подтверждение
                                 в проекте висит на форме (ui-feedback.js), и на одной форме
                                 спрашивало бы и про обычную выдачу; к тому же requestSubmit
                                 после диалога теряет значение кнопки-сабмиттера. -->
                            <form method="post" action="/api/v1/admin/salons/{s.id}/grant-access"
                                  class="adm-form"
                                  data-confirm="Открыть «{_esc(s.name)}» доступ БЕССРОЧНО? Платить салон больше не будет."
                                  data-confirm-label="Открыть бессрочно">
                                <input type="hidden" name="forever" value="1">
                                {_btn("Бессрочно")}
                            </form>
                        </div>
                        <form method="post" action="/api/v1/admin/salons/{s.id}/set-plan" class="adm-form">
                            <label class="adm-field">
                                <span class="adm-field-label">Тариф</span>
                                <select name="plan" class="r-input adm-input adm-select"
                                        aria-label="Тариф салона">{plan_options}</select>
                            </label>
                            {_btn("Сменить тариф")}
                        </form>
                    </div>
                </section>
            </div>

            <section class="adm-danger">
                <h4 class="adm-danger__title">Опасные действия</h4>
                <div class="adm-actions">
                    <form method="post" action="/api/v1/admin/salons/{s.id}/revoke-access" class="adm-form"
                          data-confirm="Снять доступ у «{_esc(s.name)}»? Салон уйдёт из каталога."
                          data-confirm-label="Снять">
                        {_btn("Снять доступ", "danger")}
                    </form>
                    {delete_form}
                </div>
            </section>
        </article>"""
        return cards or '<p class="adm-empty">Салонов нет</p>'

    active = [s for s in salons if not s.is_deleted and s.is_active and s.id in live_ids]
    blocked = [s for s in salons if not s.is_deleted and not (s.is_active and s.id in live_ids)]
    deleted = [s for s in salons if s.is_deleted]
    sections = (
        ("Действующие", active),
        ("Заблокированные", blocked),
        ("Удаленные", deleted),
    )
    groups_html = "".join(
        f'<section class="adm-salon-section"><h3 class="adm-section-title">{title} ({len(group)})</h3>'
        f'<div class="adm-list">{render_cards(group)}</div></section>'
        for title, group in sections
    )

    return f"""
    <div class="tab-content" id="tab-salons">
        <h2 class="adm-tab-title">Салоны ({len(salons)})</h2>
        {groups_html}
    </div>
    """


# ── ВКЛАДКА: ЖАЛОБЫ НА ФОТО ──────────────────────────────────────────────────
def _reports_tab(reports):
    rows = ""
    for r in reports:
        thumb = (f'<a href="{_esc(r["url"])}" target="_blank" rel="noopener">'
                 f'{_thumb(r["url"], "md")}</a>') if r["url"] else "—"
        resolve = (
            f'<div class="adm-danger adm-danger--inline">'
            f'<form method="post" action="/api/v1/admin/reports/{r["id"]}/resolve" class="adm-form" '
            f'data-confirm="Удалить фото и закрыть жалобу?" data-confirm-label="Подтвердить">'
            f'{_btn(f"{ICON_TRASH} Удалить фото", "danger")}</form></div>'
        )
        dismiss = (
            f'<form method="post" action="/api/v1/admin/reports/{r["id"]}/dismiss" class="adm-form">'
            f'{_btn("Оставить")}</form>'
        )
        rows += f"""<tr>
            <td>{thumb}</td>
            <td>{_esc(r["salon"])}</td>
            <td>{_esc(r["reporter"])}</td>
            <td>{_esc(r["reason"]) or '<span class="text-muted">—</span>'}</td>
            <td><div class="adm-actions">{dismiss}{resolve}</div></td>
        </tr>"""
    if not rows:
        rows = '<tr><td colspan="5" class="adm-empty">Открытых жалоб нет</td></tr>'
    return f"""
    <div class="tab-content" id="tab-reports">
        <h2 class="adm-tab-title">Жалобы на фото ({len(reports)})</h2>
        <p class="adm-lead">«Удалить фото» — жалоба обоснована, фото убирается. «Оставить» — жалоба отклонена.</p>
        <div class="adm-table-wrap"><table class="adm-table">
            <thead><tr><th>Фото</th><th>Салон</th><th>Пожаловался</th><th>Причина</th><th>Действия</th></tr></thead>
            <tbody>{rows}</tbody>
        </table></div>
    </div>
    """


# ── ВКЛАДКА: ОБРАЩЕНИЯ ───────────────────────────────────────────────────────
def _contest_tab(entries, phone_by_id):
    """Заявки на конкурс из ботов. Только чтение: победителей выбирают
    голосованием и жюри, а не кнопкой в админке."""
    from app.services import contest

    rows = ""
    for entry in entries:
        who = phone_by_id.get(entry.user_id) if entry.user_id else None
        who_html = _esc(who) if who else '<span class="text-muted">нет аккаунта</span>'
        rows += f"""
        <tr>
            <td class="text-muted adm-nowrap">{entry.created_at:%d.%m %H:%M}</td>
            <td>{_esc(entry.name)}</td>
            <td>{_esc(entry.city)}</td>
            <td><a href="{_esc(entry.work_url)}" target="_blank" rel="noopener">работа</a></td>
            <td>{_esc(entry.contact)}</td>
            <td>{who_html}<br><span class="adm-small text-muted">{entry.channel.value}</span></td>
        </tr>"""
    if not rows:
        rows = '<tr><td colspan="6" class="adm-empty">Заявок пока нет</td></tr>'
    return f"""
    <div class="tab-content" id="tab-contest">
        <h2 class="adm-tab-title">Конкурс ({len(entries)})</h2>
        <p class="adm-lead">
            {_esc(contest.TITLE)}. Приём заявок {_esc(contest.ru_date(contest.ENTRY_START))} —
            {_esc(contest.ru_date(contest.ENTRY_END))}, правила: <a href="/contest">/contest</a>.
            Заявки приходят из ботов, данные — со слов участника.</p>
        <div class="adm-table-wrap"><table class="adm-table">
            <thead><tr><th>Когда</th><th>Имя</th><th>Город</th><th>Работа</th><th>Связь</th><th>Аккаунт</th></tr></thead>
            <tbody>{rows}</tbody>
        </table></div>
    </div>"""


def _support_tab(requests, phone_by_id):
    """Обращения из ботов. Ответ уходит человеку его же каналом."""
    from app.services.support import STATUS_LABELS, TOPIC_LABELS, source_label

    rows = ""
    for r in requests:
        who = phone_by_id.get(r.user_id) if r.user_id else None
        who_html = _esc(who) if who else '<span class="text-muted">не авторизован</span>'
        photos = ""
        for url in (r.photos or []):
            photos += (f'<a href="{_esc(url)}" target="_blank" rel="noopener">'
                       f'{_thumb(url, "sm")}</a>')
        rating = f' · оценка {r.rating}/5' if r.rating else ""

        if r.answer:
            action = (f'<div class="adm-small text-muted">Ответ: '
                      f'{_esc(r.answer[:160])}</div>')
        else:
            action = (
                f'<form method="post" action="/api/v1/admin/support/{r.id}/answer" '
                f'class="adm-answer">'
                f'<textarea name="answer" rows="2" required minlength="2" '
                f'placeholder="Ответ человеку…" aria-label="Ответ человеку" class="r-input adm-textarea"></textarea>'
                f'{_btn("Отправить")}</form>'
            )

        rows += f"""<tr>
            <td class="adm-nowrap">№{r.id}<br>
                <span class="adm-small text-muted">{r.created_at:%d.%m %H:%M}</span></td>
            <td class="adm-nowrap">{_esc(TOPIC_LABELS[r.topic])}{rating}<br>
                <span class="adm-small text-muted">{_esc(source_label(r))} · {_esc(STATUS_LABELS[r.status])}</span></td>
            <td>{who_html}</td>
            <td class="adm-col-text">{_esc(r.text)}<div class="adm-thumbs">{photos}</div></td>
            <td>{action}</td>
        </tr>"""

    if not rows:
        rows = '<tr><td colspan="5" class="adm-empty">Обращений нет</td></tr>'
    return f"""
    <div class="tab-content" id="tab-support">
        <h2 class="adm-tab-title">Обращения ({len(requests)})</h2>
        <p class="adm-lead">
            Пришли из ботов Telegram, MAX и ВКонтакте. Во ВКонтакте два сообщества: «клиенты» и
            «бизнес» — пометка рядом со статусом. Ответ уходит человеку тем же каналом
            (и в то же сообщество), которым он написал, и закрывает обращение.</p>
        <div class="adm-table-wrap"><table class="adm-table adm-table--support">
            <thead><tr><th>Когда</th><th>Тема</th><th>От кого</th><th>Текст</th><th>Ответ</th></tr></thead>
            <tbody>{rows}</tbody>
        </table></div>
    </div>
    """


# ── ВКЛАДКА: ОТЗЫВЫ ──────────────────────────────────────────────────────────
def _subscription_cell(s) -> str:
    """Тариф, статус и срок доступа салона.

    Цвета берём из токенов: тут стояли var(--color-warning) / var(--color-success) / var(--color-danger) мимо
    палитры продукта."""
    from datetime import datetime, timezone
    from app.services.tariffs import TARIFF_CATALOG

    tariff = TARIFF_CATALOG.get(getattr(s, "business_tier", None))
    plan = tariff.name if tariff else (getattr(s, "business_tier", None) or "—")
    status_tone = {
        "NONE": ("нет тарифа", "is-none"),
        "TRIALING": ("пробный", "is-trial"),
        "ACTIVE": ("оплачен", "is-active"),
        "PAST_DUE": ("платёж не прошёл", "is-failed"),
        "CANCELED": ("отменена", "is-none"),
    }
    raw = getattr(s.subscription_status, "name", str(s.subscription_status))
    label, tone = status_tone.get(raw, (raw, "is-none"))

    until = getattr(s, "access_until", None)
    if until is None:
        access = '<span class="adm-sub is-failed">доступа нет</span>'
    else:
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        live = until > datetime.now(timezone.utc)
        access = (f'<span class="adm-sub {"is-active" if live else "is-failed"}">'
                  f'до {until.strftime("%d.%m.%Y")}{"" if live else " (истёк)"}</span>')

    pending = float(getattr(s, "pending_proration", 0) or 0)
    pending_html = (f'<span class="adm-sub is-trial">доплата {int(round(pending))} ₽</span>'
                    if pending > 0 else "")

    return (f'<span>Тариф: <strong>{plan}</strong></span>'
            f'<span class="adm-sub {tone}">{label}</span>{access}{pending_html}')


def _reviews_tab(reviews, client_by_id, master_name_by_id, salon_name_by_id):
    rows = ""
    for r in reviews:
        stars = ICON_STAR_FILLED * int(r.rating or 0)
        delete = (
            f'<div class="adm-danger adm-danger--inline">'
            f'<form method="post" action="/api/v1/admin/reviews/{r.id}/delete" class="adm-form" '
            f'data-confirm="Удалить отзыв #{r.id}?" data-confirm-label="Подтвердить">'
            f'{_btn("Удалить", "danger")}</form></div>'
        )
        rows += f"""<tr>
            <td>{r.id}</td>
            <td>{_esc(client_by_id.get(r.client_id, "—"))}</td>
            <td>{_esc(master_name_by_id.get(r.master_id, "—"))}</td>
            <td>{_esc(salon_name_by_id.get(r.salon_id, "—"))}</td>
            <td class="adm-nowrap">{stars}</td>
            <td>{_esc(r.comment) or "—"}</td>
            <td>{delete}</td>
        </tr>"""
    return f"""
    <div class="tab-content" id="tab-reviews">
        <h2 class="adm-tab-title">Отзывы ({len(reviews)})</h2>
        <div class="adm-table-wrap"><table class="adm-table">
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
            <td class="adm-nowrap">{when}</td>
            <td>{_esc(actor_by_id.get(a.actor_id, "#"+str(a.actor_id)))}</td>
            <td>{_esc(a.action)}</td>
            <td>{_esc(a.target_type)} #{a.target_id if a.target_id is not None else "—"}</td>
            <td>{_esc(a.detail)}</td>
        </tr>"""
    body = rows or '<tr><td colspan="5" class="adm-empty">Пока нет записей</td></tr>'
    return f"""
    <div class="tab-content" id="tab-audit">
        <h2 class="adm-tab-title">Аудит действий ({len(audits)})</h2>
        <div class="adm-table-wrap"><table class="adm-table">
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
        out += f'<div class="adm-alert adm-alert--err">{ICON_ALERT_TRIANGLE} {_esc(err)}</div>'
    if ok:
        out += f'<div class="adm-alert adm-alert--ok">{ICON_CIRCLE_CHECK} {_esc(ok)}</div>'
    if temp_pw:
        out += (f'<div class="adm-alert adm-alert--ok">{ICON_LOCK} Временный пароль для {_esc(temp_for)}: '
                f'<code class="adm-code">{_esc(temp_pw)}</code> — передайте пользователю, он виден один раз.</div>')
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

    # Обращения из ботов — вкладка доступна ЛЮБОМУ модератору, поэтому данные
    # грузим до ветки is_senior (иначе у обычного модератора переменных нет).
    from app.models.models import SupportRequest, SupportStatus
    support_requests = (await db.execute(
        select(SupportRequest).order_by(SupportRequest.created_at.desc()).limit(200)
    )).scalars().all()
    support_new = [r for r in support_requests if r.status == SupportStatus.NEW]
    support_tab = _support_tab(support_requests, phone_by_id)

    from app.models.models import ContestEntry
    contest_entries = (await db.execute(
        select(ContestEntry).order_by(ContestEntry.created_at.desc()).limit(300)
    )).scalars().all()
    contest_tab = _contest_tab(contest_entries, phone_by_id)

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
        # «Живой» салон и «принимающая» карточка — по тем же правилам, что
        # каталог (решение 0016, п. 4): иначе админка показывала «активный»
        # салон у человека, удалившего аккаунт.
        live_salon_ids = set((await db.execute(
            select(Salon.id).where(salon_has_live_owner())
        )).scalars().all())
        self_deleted = set((await db.execute(
            select(AdminAudit.target_id).where(AdminAudit.action == "delete_own_account")
        )).scalars().all())
        # Пометка видна, только пока аккаунт отключён (см. _user_status):
        # восстановленного админом человека она не преследует.
        master_by_uid = {m.user_id: m for m in masters}
        salons_active = sum(
            1 for s in salons if s.is_active and not s.is_deleted and s.id in live_salon_ids
        )
        overview = await _overview(db, users, salons_active)
        users_tab = _users_tab(users, user.id, master_by_uid, self_deleted)
        salons_tab = _salons_tab(salons, phone_by_id, live_salon_ids)
        reviews_tab = _reviews_tab(reviews, phone_by_id, master_name_by_id, salon_name_by_id)
        audit_tab = _audit_tab(audits, phone_by_id)

    allowed_tabs = (
        {"overview", "users", "applications", "models", "reports", "salons",
         "reviews", "audit", "support", "contest"}
        if is_senior else {"applications", "models", "reports", "support", "contest"}
    )
    default_tab = "overview" if is_senior else "applications"
    _tab = q.get("tab", default_tab)
    active_tab = _tab if _tab in allowed_tabs else default_tab
    pending_badge = _count(len(pending), "warning")
    models_badge = _count(len(pending_models), "warning")
    reports_badge = _count(len(reports_data), "danger")
    contest_badge = _count(len(contest_entries), "accent")
    support_badge = _count(len(support_new), "info")

    tab_nav = ""
    if is_senior:
        tab_nav += f'<button class="tab-btn" data-tab="overview" onclick="switchTab(\'overview\')">{ICON_CHART_COLUMN} Обзор</button>'
        tab_nav += f'<button class="tab-btn" data-tab="users" onclick="switchTab(\'users\')">{ICON_USERS} Пользователи</button>'
    tab_nav += f'<button class="tab-btn" data-tab="applications" onclick="switchTab(\'applications\')">{ICON_FILE_TEXT} Заявки{pending_badge}</button>'
    tab_nav += f'<button class="tab-btn" data-tab="models" onclick="switchTab(\'models\')">{ICON_MODEL} Модели{models_badge}</button>'
    tab_nav += f'<button class="tab-btn" data-tab="reports" onclick="switchTab(\'reports\')">{ICON_FLAG} Жалобы{reports_badge}</button>'
    tab_nav += f'<button class="tab-btn" data-tab="support" onclick="switchTab(\'support\')">{ICON_MESSAGE_CIRCLE} Обращения{support_badge}</button>'
    tab_nav += f'<button class="tab-btn" data-tab="contest" onclick="switchTab(\'contest\')">{ICON_FILE_TEXT} Конкурс{contest_badge}</button>'
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
</head>
<body>
    {render_header("admin", user)}
    <main class="admin-main">
        <h1 class="text-display adm-title">{ICON_SHIELD_CHECK} Панель модератора</h1>
        <p class="text-muted adm-who">{_esc(user.full_name or user.phone)} · {role_label}</p>
        {_banner(q)}
        <div class="tab-nav" role="tablist">
            {tab_nav}
        </div>
        {overview}
        {users_tab}
        {applications_tab}
        {model_applications_tab}
        {reports_tab}
        {support_tab}
        {contest_tab}
        {salons_tab}
        {reviews_tab}
        {audit_tab}
    </main>
    {render_footer(user, "business")}
    <script>
        function switchTab(name) {{
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.toggle('active', c.id === 'tab-' + name));
            history.replaceState(null, '', '/admin?tab=' + name);
        }}
        function filterTable(inputId, tableId) {{
            var q = document.getElementById(inputId).value.toLowerCase();
            document.querySelectorAll('#' + tableId + ' tbody tr').forEach(function(tr) {{
                tr.hidden = tr.textContent.toLowerCase().indexOf(q) === -1;
            }});
        }}
        switchTab({active_tab!r});
    </script>
</body>
</html>"""
