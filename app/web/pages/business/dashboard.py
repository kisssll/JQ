# app/web/pages/business/dashboard.py
import re

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta
from app.models.models import (
    Salon, Master, Service, Promotion, Booking, Review, BookingStatus,
    SalonMember, User as UserModel, SalonModerationStatus,
    SalonLoyaltySettings, LoyaltyOffer,
)
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
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
        return await render_payroll_tab(db, salon, masters, master_ids, qp.get("period")) if perms["manage_payroll"] else ""

    if tab_name == "cost":
        return await render_cost_tab(db, salon, masters, master_ids, qp.get("period")) if perms["view_finances"] else ""

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
        return await render_promo_models_tab(db, salon) if perms["manage_masters"] else ""

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

    return ""


async def render_business_dashboard(db: AsyncSession, user, salon: Salon, membership: SalonMember, query_params=None) -> str:
    """Бизнес-панель. Поддержка параметра partial=1 для AJAX-подгрузки вкладок."""
    query_params = query_params or {}
    active_tab = query_params.get("tab", "overview")
    partial = query_params.get("partial") == "1"

    perms = _compute_perms(membership)

    # Салоны, доступные пользователю — для свитчера в шапке
    other_memberships = (await db.execute(
        select(SalonMember, Salon)
        .join(Salon, Salon.id == SalonMember.salon_id)
        .where(SalonMember.user_id == user.id, SalonMember.is_active == True)
        .order_by(Salon.name)
    )).all()

    # Если членств меньше двух, но у пользователя больше одного созданного салона —
    # используем их как fallback для тестов (чтобы селектор появился)
    if len(other_memberships) <= 1 and len(user.created_salons) > 1:
        other_memberships = [(None, s) for s in user.created_salons]

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
        ('edit', ICON_SETTINGS_GEAR_SMALL, 'Редактировать салон', True),
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
        nav_buttons_html += (
            f'<button class="tab-btn{active_class}" '
            f'onclick="window.location.href=\'{_tab_href(slug)}\'">{icon} {label}</button>'
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

    # Баннер статуса заявки
    moderation_banner = ""
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
</body>
</html>"""

    return html