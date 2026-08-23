# app/web/pages/business/dashboard.py
import re

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta, timezone
from app.services.subscription import has_access
from app.models.models import (
    Salon, Master, Service, Promotion, Booking, Review, BookingStatus,
    SalonMember, User as UserModel, SalonModerationStatus, SalonSubscriptionStatus,
    SalonLoyaltySettings, LoyaltyOffer,
)
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.components.yandex_maps import render_yandex_maps_script
from app.web.components.icons import (
    ICON_LAYOUT_DASHBOARD,
    ICON_CLOCK,
    ICON_USERS,
    ICON_WALLET,
    ICON_PACKAGE,
    ICON_CHART_COLUMN,
    ICON_HEART,
    ICON_CALENDAR_DAYS,
    ICON_STAR_FILLED,
    ICON_USER_CHECK,
    ICON_SPARKLES,
    ICON_SETTINGS_GEAR_SMALL,
    ICON_PLUS,
    ICON_CREDIT_CARD,
    ICON_MESSAGE_CIRCLE,
)
from app.web.pages.business.utils import get_masters_data, get_master_ids, get_overview_revenue_data
from app.web.pages.business.tabs.overview import render_overview_tab
from app.web.pages.business.tabs.analytics import render_analytics_tab
from app.web.pages.business.tabs.promos import render_promos_tab
from app.web.pages.business.tabs.reviews import render_reviews_tab
from app.web.pages.business.tabs.schedule import render_schedule_tab
from app.web.pages.business.tabs.employees import render_employees_tab
from app.web.pages.business.tabs.services import render_services_tab
from app.web.pages.business.tabs.records import render_records_tab
from app.web.pages.business.tabs.warehouse import render_warehouse_tab
from app.web.pages.business.tabs.payroll import render_payroll_tab
from app.web.pages.business.tabs.cost import render_cost_tab
from app.web.pages.business.tabs.promo_models import render_promo_models_tab
from app.web.pages.business.tabs.my_salon import render_my_salon_tab
from app.web.pages.business.tabs.billing import render_billing_tab
from app.web.pages.business.tabs.instructions import render_instructions_tab
from app.crm.tabs.clients import render_crm_tab


_PERM_KEYS = (
    "manage_salon", "manage_owners", "manage_admins", "manage_masters",
    "manage_schedule", "manage_promotions", "manage_reviews",
    "view_finances", "manage_tariff", "view_audit_log",
    "manage_inventory", "manage_payroll",
)


def _compute_perms(membership: SalonMember) -> dict:
    return {
        key: (membership.is_creator or membership.permissions.get(key, False))
        for key in _PERM_KEYS
    }


def _int_or_none(raw):
    return int(raw) if raw and str(raw).isdigit() else None


async def _evening_deal_html(db: AsyncSession, salon: Salon, perms: dict) -> str:
    """Секция «Вечерние окна со скидкой» — только тем, кто управляет салоном.
    Дублируется во вкладках «Расписание» и «Акции» (см. компонент)."""
    if not perms.get("manage_salon"):
        return ""
    from app.services.evening_deals_service import get_deal, deal_to_dict
    from app.web.components.evening_deal import render_evening_deal_section
    deal = await get_deal(db, salon.id)
    services = (await db.execute(
        select(Service).join(Master, Master.id == Service.master_id).where(
            Master.salon_id == salon.id, Service.is_active == True,  # noqa: E712
        ).order_by(Service.name)
    )).scalars().all()
    return render_evening_deal_section(salon, services, deal_to_dict(deal))


async def render_dashboard_tab(
    db: AsyncSession, user, salon: Salon, membership: SalonMember,
    perms: dict, masters, master_ids, tab_name: str, query_params: dict,
) -> str:
    """Рендер ОДНОЙ вкладки бизнес-панели."""
    qp = query_params

    if tab_name == "overview":
        services_count = 0
        if master_ids:
            services_count = (await db.execute(
                select(func.count(Service.id)).where(Service.master_id.in_(master_ids))
            )).scalar() or 0
        promotions = (await db.execute(
            select(Promotion).where(Promotion.salon_id == salon.id)
        )).scalars().all()
        overview_data = await get_overview_revenue_data(db, master_ids)
        return await render_overview_tab(
            db, salon, masters, master_ids, services_count, promotions, **overview_data,
        )

    if tab_name == "analytics":
        return await render_analytics_tab(db, salon, master_ids) if perms["view_finances"] else ""

    if tab_name == "schedule":
        return await render_schedule_tab(
            db, salon, masters, perms["manage_schedule"],
            _int_or_none(qp.get("schedule_master_id")),
            evening_deal_html=await _evening_deal_html(db, salon, perms),
        )

    if tab_name == "employees":
        return await render_employees_tab(db, salon, masters, user, membership, perms)

    if tab_name == "services":
        return await render_services_tab(
            db, salon, masters,
            can_manage=perms["manage_masters"],
            filter_master_id=_int_or_none(qp.get("service_master")),
            filter_service_name=qp.get("service_search") or None,
        )

    if tab_name == "payroll":
        return await render_payroll_tab(db, salon, masters, master_ids, qp.get("date_from"), qp.get("date_to")) if perms["manage_payroll"] else ""

    if tab_name == "cost":
        return await render_cost_tab(db, salon, masters, master_ids, qp.get("date_from"), qp.get("date_to")) if perms["view_finances"] else ""

    if tab_name == "records":
        records_filters = {
            "date_from": qp.get("date_from"), "date_to": qp.get("date_to"),
            "master_id": qp.get("master_id"), "status": qp.get("status"),
        }
        return await render_records_tab(db, salon, masters, master_ids, records_filters, perms["manage_schedule"])

    if tab_name == "warehouse":
        if not perms["manage_inventory"]:
            return ""
        return await render_warehouse_tab(db, salon, masters, master_ids, {"audit_id": qp.get("audit_id")}, membership)

    if tab_name == "models":
        return await render_promo_models_tab(db, salon, masters) if perms["manage_masters"] else ""

    if tab_name == "promos":
        promotions = (await db.execute(
            select(Promotion).where(Promotion.salon_id == salon.id)
        )).scalars().all()
        # Загружаем настройки лояльности и предложения
        loyalty_settings = (await db.execute(
            select(SalonLoyaltySettings).where(SalonLoyaltySettings.salon_id == salon.id)
        )).scalar_one_or_none()
        loyalty_offers_result = await db.execute(
            select(LoyaltyOffer).where(LoyaltyOffer.salon_id == salon.id).order_by(LoyaltyOffer.created_at.desc())
        )
        loyalty_offers = loyalty_offers_result.scalars().all()
        return render_promos_tab(
            promotions,
            can_manage=perms["manage_promotions"],
            salon_id=salon.id,
            loyalty_settings=loyalty_settings,
            loyalty_offers=loyalty_offers,
            evening_deal_html=await _evening_deal_html(db, salon, perms),
        )

    if tab_name == "reviews":
        reviews = (await db.execute(
            select(Review).where(Review.salon_id == salon.id).order_by(Review.created_at.desc())
        )).scalars().all()
        return await render_reviews_tab(db, reviews, salon)

    if tab_name == "crm":
        return await render_crm_tab(db, salon, masters, master_ids)

    if tab_name == "edit":
        return await render_my_salon_tab(
            db, salon, user, query_params,
            can_manage_salon=perms["manage_salon"], is_creator=membership.is_creator,
        )

    if tab_name == "billing":
        active_masters = len([m for m in masters if m.is_active])
        return await render_billing_tab(db, salon, perms["manage_tariff"], active_masters)

    if tab_name == "instructions":
        return render_instructions_tab()

    return ""


async def render_business_dashboard(db: AsyncSession, user, salon: Salon, membership: SalonMember, query_params=None) -> str:
    """Бизнес-панель. Поддержка параметра partial=1 для AJAX-подгрузки вкладок."""
    query_params = query_params or {}
    active_tab = query_params.get("tab", "overview")
    partial = query_params.get("partial") == "1"

    perms = _compute_perms(membership)

    # Салоны для свитчера: объединяем членства и созданные салоны
    memberships_result = await db.execute(
        select(SalonMember, Salon)
        .join(Salon, Salon.id == SalonMember.salon_id)
        .where(
            SalonMember.user_id == user.id,
            SalonMember.is_active == True
        )
        .order_by(Salon.name)
    )
    member_salons = [(member, salon) for member, salon in memberships_result.all()]

    created_salons_result = await db.execute(
        select(Salon).where(
            Salon.creator_id == user.id,
            Salon.is_active == True
        ).order_by(Salon.name)
    )
    created_salons = created_salons_result.scalars().all()

    # Собираем уникальные салоны (по id) из обоих списков
    salons_by_id = {}
    for member, s in member_salons:
        salons_by_id[s.id] = (member, s)
    for s in created_salons:
        if s.id not in salons_by_id:
            salons_by_id[s.id] = (None, s)

    other_memberships = list(salons_by_id.values())

    # Мастера нужны большинству вкладок — грузим один раз
    masters, masters_rows = await get_masters_data(db, salon.id)
    master_ids = get_master_ids(masters)

    # Счётчики для меток вкладок
    promos_count = (await db.execute(
        select(func.count(Promotion.id)).where(Promotion.salon_id == salon.id)
    )).scalar() or 0
    reviews_count = (await db.execute(
        select(func.count(Review.id)).where(Review.salon_id == salon.id)
    )).scalar() or 0

    tab_buttons = [
        ('overview', ICON_LAYOUT_DASHBOARD, 'Обзор', True),
        ('analytics', ICON_CHART_COLUMN, 'Аналитика', perms["view_finances"]),
        ('schedule', ICON_CLOCK, 'Расписание', True),
        ('employees', ICON_USERS, 'Сотрудники', True),
        ('services', ICON_USER_CHECK, 'Услуги', True),
        ('payroll', ICON_WALLET, 'Зарплаты', perms["manage_payroll"]),
        ('cost', ICON_PACKAGE, 'Себестоимость', perms["view_finances"]),
        ('records', ICON_CALENDAR_DAYS, 'Записи', True),
        ('warehouse', ICON_PACKAGE, 'Склад', perms["manage_inventory"]),
        ('models', ICON_HEART, 'Модели', perms["manage_masters"]),
        ('promos', ICON_SPARKLES, f'Акции ({promos_count})', True),
        ('reviews', ICON_STAR_FILLED, f'Отзывы ({reviews_count})', True),
        ('crm', ICON_USER_CHECK, 'Клиенты', True),
        ('billing', ICON_CREDIT_CARD, 'Тариф', perms["manage_tariff"]),
        ('edit', ICON_SETTINGS_GEAR_SMALL, 'Редактировать салон', True),
        ('instructions', ICON_MESSAGE_CIRCLE, 'Инструкция', True),
    ]

    visible_slugs = [slug for slug, _, _, visible in tab_buttons if visible]
    if active_tab not in visible_slugs:
        active_tab = "overview"

    def _tab_href(slug: str) -> str:
        return f"/business/dashboard?salon_id={salon.id}&tab={slug}"

    nav_buttons_html = ""
    for slug, icon, label, visible in tab_buttons:
        if not visible:
            continue
        active_class = " active" if slug == active_tab else ""
        # Ссылка, а не <button onclick=window.location>: вкладка и так грузится
        # полной навигацией, но кнопкой её нельзя было открыть в новой вкладке,
        # средним кликом или без JS, и скринридер не читал её как переход.
        aria_current = ' aria-current="page"' if active_class else ""
        nav_buttons_html += (
            f'<a class="tab-btn{active_class}" href="{_tab_href(slug)}"{aria_current}>'
            f'{icon} {label}</a>'
        )

    # Рендерим ТОЛЬКО активную вкладку
    active_body = await render_dashboard_tab(
        db, user, salon, membership, perms, masters, master_ids, active_tab, query_params,
    )
    # Помечаем её active (её показ управляется классом .tab-content.active)
    pattern = re.compile(f'(id="tab-{active_tab}" class="tab-content)([^"]*)"')
    tabs_body_html = pattern.sub(r'\1\2 active"', active_body)

    # Если запрос partial — возвращаем только содержимое вкладки (без обёртки)
    if partial:
        return tabs_body_html

    switcher_html = ""
    if len(other_memberships) > 1:
        options = "".join(
            f'<option value="{s.id}"{" selected" if s.id == salon.id else ""}>{s.name}</option>'
            for _, s in other_memberships
        )
        switcher_html = f"""
        <select class="salon-switcher custom-select" onchange="window.location.href='/business/dashboard?salon_id=' + this.value">
            {options}
        </select>"""

    # Ссылка «Добавить салон» — только для настоящих владельцев (создателей
    # своих салонов), чтобы не путать нанятых сотрудников: у них тоже есть
    # доступ к /business/register-salon (по сайт-роли BUSINESS), но кнопка
    # в панели чужого салона выглядела бы так, будто она про этот салон.
    add_salon_html = ""
    if membership.is_creator:
        add_salon_html = f'<a class="salon-switcher-add" href="/business/register-salon">{ICON_PLUS} Добавить салон</a>'

    # Баннер статуса заявки + модальное предупреждение (см. publish_gate_modal_html
    # ниже) — оба про один и тот же случай «модерация пройдена, тариф не выбран»,
    # баннер держит объяснение постоянно на экране, модалка обращает на него внимание
    # сразу при заходе в панель (один раз за сессию, см. dashboard.js).
    moderation_banner = ""
    show_publish_gate_modal = False
    if salon.moderation_status == SalonModerationStatus.PENDING:
        moderation_banner = (
            '<div style="background:#fef3c7;border:1px solid #f59e0b;color:#92400e;'
            'padding:0.9rem 1.1rem;border-radius:0.75rem;margin:1.5rem 0 0;font-size:0.9rem">'
            '<b>Заявка на рассмотрении.</b> Можно настраивать салон (услуги, мастера, фото), '
            'но клиентам он пока не виден и запись закрыта — откроются после подтверждения платформой.</div>'
        )
    elif salon.moderation_status == SalonModerationStatus.REJECTED:
        import html as _html
        reason = f' Причина: {_html.escape(salon.rejection_reason)}.' if salon.rejection_reason else ''
        moderation_banner = (
            '<div style="background:#fee2e2;border:1px solid #ef4444;color:#991b1b;'
            'padding:0.9rem 1.1rem;border-radius:0.75rem;margin:1.5rem 0 0;font-size:0.9rem">'
            f'<b>Заявка отклонена.</b>{reason} Свяжитесь с поддержкой.</div>'
        )
    elif salon.published_at is None and salon.subscription_status == SalonSubscriptionStatus.NONE:
        # Одобрен, но тариф ещё не выбран — публикация требует оплаты (хотя бы
        # запуска пробного периода), модерация сама по себе доступ не даёт.
        can_publish = perms.get("manage_salon") if isinstance(perms, dict) else False
        billing_link = (
            f'<a href="/business/dashboard?salon_id={salon.id}&tab=billing" '
            'style="display:inline-block;margin-top:0.75rem;background:#16a34a;color:#fff;'
            'text-decoration:none;padding:0.6rem 1.2rem;border-radius:0.6rem;font-size:0.9rem;'
            f'font-weight:600">{ICON_SPARKLES} Выбрать тариф</a>'
        ) if can_publish else ''
        moderation_banner = (
            '<div style="background:#dcfce7;border:1px solid #16a34a;color:#166534;'
            'padding:0.9rem 1.1rem;border-radius:0.75rem;margin:1.5rem 0 0;font-size:0.9rem">'
            '<b>Ваш салон прошёл модерацию!</b> Осталось выбрать тариф — без него '
            'публикация недоступна. До этого салон виден только вам.'
            f'{billing_link}</div>'
        )
        show_publish_gate_modal = can_publish
    elif salon.published_at is None:
        # Тариф выбран (хотя бы пробный период) — можно публиковать.
        # Пока не опубликован, салон полностью непубличен (нет в каталоге, запись
        # закрыта). Кнопка шлёт AJAX → на успехе перезагружает панель (см.
        # dashboard.js, #salonPublishBtn). Показываем только тем, кто вправе
        # управлять салоном; остальным — просто поздравление.
        can_publish = perms.get("manage_salon") if isinstance(perms, dict) else False
        publish_btn = (
            f'<button type="button" id="salonPublishBtn" data-salon-id="{salon.id}" '
            'style="margin-top:0.75rem;background:#16a34a;color:#fff;border:none;'
            'padding:0.6rem 1.2rem;border-radius:0.6rem;font-size:0.9rem;font-weight:600;cursor:pointer">'
            f'{ICON_SPARKLES} Опубликовать салон</button>'
        ) if can_publish else ''
        moderation_banner = (
            '<div style="background:#dcfce7;border:1px solid #16a34a;color:#166534;'
            'padding:0.9rem 1.1rem;border-radius:0.75rem;margin:1.5rem 0 0;font-size:0.9rem">'
            '<b>Ваш салон прошёл модерацию!</b> Осталось опубликовать его — после '
            'этого он появится в каталоге, поиске и откроется запись клиентов. '
            'До публикации салон виден только вам.'
            f'{publish_btn}</div>'
        )
    else:
        # Уже опубликован — здесь смотрим не на факт публикации, а на оплату:
        # 1) уже скрыт биллингом за неоплату (истёк триал/грейс-период PAST_DUE,
        #    (истёк access_until) — «появится после оплаты»;
        # 2) ещё не скрыт, но оплаты не было (идёт триал) или последний платёж
        #    не прошёл (PAST_DUE) — предупреждаем заранее, пока не поздно.
        now = datetime.now(timezone.utc)
        can_manage_tariff = perms.get("manage_tariff") if isinstance(perms, dict) else False

        def _billing_link(accent: str) -> str:
            if not can_manage_tariff:
                return ''
            return (
                f'<a href="/business/dashboard?salon_id={salon.id}&tab=billing" '
                f'style="display:inline-block;margin-top:0.75rem;background:#fff;color:{accent};'
                'text-decoration:none;padding:0.6rem 1.2rem;border-radius:0.6rem;font-size:0.9rem;'
                f'font-weight:600;border:1px solid {accent}">{ICON_SPARKLES} Оплатить подписку</a>'
            )

        # Доступ по тарифу истёк — каталог его уже не показывает (фильтр по
        # access_until), поэтому предупреждаем владельца прямо в шапке.
        if not has_access(salon):
            moderation_banner = (
                '<div style="background:#fee2e2;border:1px solid #ef4444;color:#991b1b;'
                'padding:0.9rem 1.1rem;border-radius:0.75rem;margin:1.5rem 0 0;font-size:0.9rem">'
                '<b>Салон скрыт из каталога.</b> Подписка не оплачена — салон снова появится '
                'в общем списке платформы и откроется для записи сразу после оплаты.'
                f'{_billing_link("#ef4444")}</div>'
            )
        elif salon.subscription_status == SalonSubscriptionStatus.PAST_DUE:
            moderation_banner = (
                '<div style="background:#fee2e2;border:1px solid #ef4444;color:#991b1b;'
                'padding:0.9rem 1.1rem;border-radius:0.75rem;margin:1.5rem 0 0;font-size:0.9rem">'
                '<b>Не удалось списать оплату.</b> Обновите привязанную карту или оплатите '
                'вручную — иначе салон скоро пропадёт из каталога.'
                f'{_billing_link("#ef4444")}</div>'
            )
        elif salon.subscription_status == SalonSubscriptionStatus.TRIALING and salon.trial_ends_at:
            days_left = max(0, (salon.trial_ends_at - now).days)
            deadline = salon.trial_ends_at.strftime('%d.%m.%Y')
            days_word = 'день' if days_left == 1 else ('дня' if 2 <= days_left <= 4 else 'дней')
            moderation_banner = (
                '<div style="background:#fef3c7;border:1px solid #f59e0b;color:#92400e;'
                'padding:0.9rem 1.1rem;border-radius:0.75rem;margin:1.5rem 0 0;font-size:0.9rem">'
                f'<b>Идёт бесплатный пробный период</b> — осталось {days_left} {days_word} '
                f'(до {deadline}). Оплатите подписку, чтобы салон не пропал из каталога '
                'после его окончания.'
                f'{_billing_link("#f59e0b")}</div>'
            )

    publish_gate_modal_html = ""
    if show_publish_gate_modal:
        publish_gate_modal_html = f"""
        <div class="publish-gate-modal-overlay" id="publishGateModal" data-salon-id="{salon.id}">
            <div class="publish-gate-modal-box">
                <button type="button" class="publish-gate-modal-close" id="publishGateModalClose">&times;</button>
                <div class="publish-gate-icon">💳</div>
                <h2>Салон пока не виден клиентам</h2>
                <p>Модерация пройдена, но салон появится в общем каталоге платформы —
                видимым для клиентов и открытым для записи — только после оплаты
                тарифа. Как только оплатите (или запустите пробный период),
                салон сразу появится в списке.</p>
                <a href="/business/dashboard?salon_id={salon.id}&tab=billing" class="btn-primary">
                    {ICON_SPARKLES} Выбрать тариф
                </a>
            </div>
        </div>"""

    header_html = f"""
    <div class="dashboard-header">
        <div class="dashboard-header-inner">
            <div class="header-title">
                <h1>Панель салона</h1>
                <p>Салон «{salon.name}» • {salon.address.split(',')[0] if salon.address else 'Адрес не указан'}</p>
            </div>
            <div class="header-controls">
                {switcher_html}
                {add_salon_html}
                <span class="dashboard-badge">
                    {ICON_SPARKLES} Бизнес PRO
                </span>
            </div>
        </div>
    </div>
    """

    html = f"""<!DOCTYPE html>
<html lang="ru" class="dashboard-page">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Бизнес-панель — {salon.name} — руми</title>
    {get_base_styles()}
    {render_yandex_maps_script()}
</head>
<body>
    {render_header("business")}
    {render_sidebar("business_dashboard", user)}
    <main style="margin-right:0;padding-top:0">
        {header_html}
        <div class="section-container" style="padding-top: 0;">{moderation_banner}</div>
        <div class="section-container" style="padding-top: 1.5rem;">
            <div class="tab-nav">
                {nav_buttons_html}
            </div>
            {tabs_body_html}
        </div>
    </main>
    {render_footer(user)}
    {publish_gate_modal_html}
</body>
</html>"""

    return html