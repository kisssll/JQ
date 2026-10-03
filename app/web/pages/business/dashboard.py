# app/web/pages/business/dashboard.py
from app.web.components.escaping import e
import re

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, or_, select
from datetime import datetime, timedelta, timezone
from app.services.subscription import has_access
from app.services import (
    booking_readiness, growth_checklist, panel_guide, panel_sections, panel_tour,
)
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
    ICON_SLIDERS,
    ICON_MINUS_SMALL,
    ICON_ARROW_UP_TINY,
    ICON_ARROW_DOWN_TINY,
    ICON_CHECK_SMALL,
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
from app.web.components.panel_tour import (
    render_tour_bar, render_tour_invite,
)
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
    visible_keys=None, tour_on: bool = False,
) -> str:
    """Рендер ОДНОЙ вкладки бизнес-панели.

    visible_keys и tour_on нужны двум вкладкам. «Инструкции»: справочник
    описывает ТЕ разделы, которые у человека есть, и ведёт в них живыми
    ссылками (решение 0009, п. 7). «Обзору»: группа 3 пути к первому клиенту
    зовёт в «Записи», «Аналитику», «Отзывы» и «Клиентов», а раздел, которого у
    человека нет, ссылкой становиться не должен. Список передаётся готовым, тот
    же, по которому строится меню: иначе у справочника, у панели и у пути
    разошлось бы представление о том, что человеку доступно.
    """
    qp = query_params

    if tab_name == "overview":
        # Услуги, которые клиент МОЖЕТ выбрать: активные и не модельные, тем же
        # набором условий, что отбирает гостевая страница записи (у услуги
        # бывает и master_id, и назначение — в форме заполняется и то, и то, но
        # исторические строки бывают только с master_id). Прежний запрос считал
        # все услуги по одному назначению: число никуда не выводилось, а теперь
        # по нему живёт пункт «услуг нет» — и он не имеет права соврать.
        services_count = 0
        if master_ids:
            services_count = (await db.execute(
                select(func.count(Service.id)).where(
                    or_(
                        Service.master_id.in_(master_ids),
                        Service.assigned_masters.any(Master.id.in_(master_ids)),
                    ),
                    Service.is_active == True,  # noqa: E712
                    Service.is_model_practice == False,  # noqa: E712
                )
            )).scalar() or 0
        promotions = (await db.execute(
            select(Promotion).where(Promotion.salon_id == salon.id)
        )).scalars().all()
        overview_data = await get_overview_revenue_data(db, master_ids)
        solo = panel_sections.is_solo(salon)
        # «Есть ли записи вообще» — чтобы не показывать соло-мастеру пустой
        # график выручки. Именно за всё время, а не за неделю: неделя без
        # записей бывает и у работающего салона. Спрашиваем существование, а не
        # количество: точное число здесь не нужно, а выборка останавливается на
        # первой же строке.
        has_any_booking = bool(master_ids) and (await db.scalar(
            select(Booking.id).where(Booking.master_id.in_(master_ids)).limit(1)
        )) is not None
        # Блок готовности и ссылку показываем тому, кто вправе менять салон:
        # каждое действие в блоке ведёт в раздел, который иначе ему не откроется,
        # — получился бы список ссылок, возвращающих человека обратно в «Обзор».
        can_manage = bool(perms.get("manage_salon"))
        # Путь к первому клиенту: группу 1 считает booking_readiness, группу 2
        # — growth_checklist. Второй получает на руки всё, что панель уже
        # посчитала (услуги, акции, причины готовности, «записи вообще есть»), и
        # добавляет не больше двух своих запросов: «Обзор» — самый посещаемый
        # раздел панели, и его однажды разгоняли с девяти секунд до двух с
        # половиной.
        readiness = (
            await booking_readiness.collect(db, salon, masters, solo=solo)
            if can_manage else None
        )
        checklist = None
        next_links = ()
        if readiness is not None:
            # Удалённому профилю группа 2 не показывается вовсе: «обложка не
            # выбрана» салону, которого публично нет, — ровно тот шум, от
            # которого booking_readiness закрывается одной строкой.
            deleted = any(i.key == "salon_deleted" for i in readiness.issues)
            if not deleted:
                checklist = await growth_checklist.collect(
                    db, salon, solo=solo, master_ids=master_ids,
                    services_total=services_count, promotions=promotions,
                    readiness=readiness, has_any_booking=has_any_booking,
                )
                # Группа 3 — только когда в первых двух дел не осталось
                # (решение 0010, п. 4). Warnings тоже дело: закрытый путь
                # записи из двух — не «всё готово».
                if not readiness.issues and checklist.all_done:
                    next_links = growth_checklist.next_links(
                        salon, solo=solo, visible_keys=visible_keys,
                    )
        return await render_overview_tab(
            db, salon, masters, master_ids, services_count, promotions, **overview_data,
            solo=solo,
            readiness=readiness,
            checklist=checklist,
            next_links=next_links,
            show_booking_link=can_manage,
            # Та же видимость, что у вкладки: раздел включён у салона И право
            # есть (см. _perm_of ниже — у «Моделей» это manage_masters).
            show_models_invite=(
                panel_sections.is_enabled(salon, "models")
                and bool(perms.get("manage_masters"))
            ),
            has_any_booking=has_any_booking,
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
            solo=panel_sections.is_solo(salon),
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
        return render_instructions_tab(
            salon_id=salon.id, mode=salon.panel_mode,
            # Ссылку «пройти знакомство заново» показываем тому, кто тур в
            # принципе увидит: у участника без manage_salon она ничего бы не
            # открыла (см. panel_tour.decide).
            can_tour=bool(perms.get("manage_salon")),
            visible_keys=visible_keys,
            tour_on=tour_on,
        )

    return ""


async def _already_working(db: AsyncSession, salon: Salon, masters, master_ids) -> bool:
    """«У этого уже всё работает»: записаться можно и запись хотя бы одна есть.

    Такому владельцу тур сам не всплывает — его ведут по шагам «как попасть в
    ленту», которые он уже прошёл (решение 0008, п. 5). Условие «можно
    записаться» не переписываем: его считает booking_readiness, выписанный из
    кода самой записи.
    """
    readiness = await booking_readiness.collect(
        db, salon, masters, solo=panel_sections.is_solo(salon),
    )
    if readiness.blocking:
        return False
    if not master_ids:
        return False
    # Существование, а не количество: выборка останавливается на первой строке.
    return (await db.scalar(
        select(Booking.id).where(Booking.master_id.in_(master_ids)).limit(1)
    )) is not None


async def _save_tour_state(db: AsyncSession, user, decision) -> None:
    """Записать, где человек в туре.

    Пишем на GET, и это намеренно: вкладки панели открываются полной
    навигацией, поэтому шаг — обычный переход. Запись идемпотентна (тот же шаг
    — то же значение), своих данных не удаляет и касается только самого
    человека, так что цена такого GET — одна строка UPDATE.
    """
    changed = False
    if decision.start_now and user.panel_tour_started_at is None:
        # Только если ещё не ставили: «запустили ВПЕРВЫЕ» перезаписать нельзя,
        # иначе по этой отметке не посчитать, сколько людей тур увидели.
        user.panel_tour_started_at = datetime.now(timezone.utc)
        changed = True
    if decision.save_step and decision.save_step != user.panel_tour_step:
        user.panel_tour_step = decision.save_step
        changed = True
    if decision.finish_now and user.panel_tour_done_at is None:
        user.panel_tour_done_at = datetime.now(timezone.utc)
        changed = True
    if decision.clear_done and user.panel_tour_done_at is not None:
        user.panel_tour_done_at = None
        changed = True
    if changed:
        await db.commit()


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

    # Итоговая видимость раздела — И то, и другое: раздел включён у салона
    # (режим + переключатели владельца, см. panel_sections) И у человека есть
    # право. Две разные причины, их нельзя складывать в одну: режим — про то,
    # что есть в бизнесе, право — про то, кто из команды что может.
    enabled_sections = panel_sections.enabled_keys(salon)
    mode = salon.panel_mode
    # Подписи панели — из реестра (решение 0009, п. 6). У соло-мастера салона
    # нет, есть он сам, и плашки статуса в этом режиме говорят другое.
    w = panel_guide.words_for(mode)
    _icons = {
        'overview': ICON_LAYOUT_DASHBOARD, 'analytics': ICON_CHART_COLUMN,
        'schedule': ICON_CLOCK, 'employees': ICON_USERS, 'services': ICON_USER_CHECK,
        'payroll': ICON_WALLET, 'cost': ICON_PACKAGE, 'records': ICON_CALENDAR_DAYS,
        'warehouse': ICON_PACKAGE, 'models': ICON_HEART, 'promos': ICON_SPARKLES,
        'reviews': ICON_STAR_FILLED, 'crm': ICON_USER_CHECK, 'billing': ICON_CREDIT_CARD,
        'edit': ICON_SETTINGS_GEAR_SMALL, 'instructions': ICON_MESSAGE_CIRCLE,
    }
    _perm_of = {
        'analytics': perms["view_finances"],
        'payroll': perms["manage_payroll"],
        'cost': perms["view_finances"],
        'warehouse': perms["manage_inventory"],
        'models': perms["manage_masters"],
        'billing': perms["manage_tariff"],
    }
    _counts = {'promos': promos_count, 'reviews': reviews_count}

    def _permitted(slug: str) -> bool:
        """Право на раздел — вторая, независимая причина его не показывать."""
        return bool(_perm_of.get(slug, True))

    def _label_of(slug: str) -> str:
        text = panel_sections.label(slug, mode)
        return f'{text} ({_counts[slug]})' if slug in _counts else text

    # Порядок разделов — настройка владельца (он расставляет их в самой панели),
    # поэтому идём по ordered_keys, а не по каноническому ALL_KEYS.
    visible_slugs = [slug for slug in panel_sections.ordered_keys(salon) if _permitted(slug)]
    # Вернуть предлагаем только те скрытые разделы, которые человеку в принципе
    # покажут: плюс на разделе без права ничего бы не изменил.
    # Раздела, которого в режиме не существует, в «скрытых» быть не должно:
    # плюс на нём вернул бы в панель вкладку, чьё содержимое уже лежит в другой
    # (в соло это «Редактировать салон», см. panel_sections.available_keys).
    available_sections = panel_sections.available_keys(mode)
    locked = panel_sections.locked_keys(mode)
    hidden_slugs = [
        slug for slug in panel_sections.ALL_KEYS
        if slug not in enabled_sections and slug in available_sections and _permitted(slug)
    ]

    # Прямой ?tab=edit в соло — не ошибка и не «Обзор»: вкладки «Редактировать
    # салон» в этом режиме нет, но её содержимое никуда не делось, оно в «Моей
    # карточке мастера» (решение 0009, п. 2). Так же приходят старые ссылки,
    # закладки и редирект /business/my-salon, который режима не знает.
    settings_tab = panel_sections.settings_key(mode)
    if active_tab == "edit" and settings_tab != "edit":
        active_tab = settings_tab

    # Выключенный раздел не открывается и по прямой ссылке — проверка стоит ДО
    # рендера вкладки, поэтому и ?tab=, и ?tab=&partial=1 уходят в «Обзор».
    if active_tab not in visible_slugs:
        active_tab = "overview"

    # ----- Знакомство с панелью (тур, решение 0008) -----
    # Состав шагов строится из ТЕХ ЖЕ visible_slugs, что и меню: иначе тур увёл
    # бы в раздел, которого у человека нет. Решение о показе — в panel_tour,
    # здесь остаются только чтение запроса, запись состояния и разметка.
    # При partial=1 тура нет вовсе: ответ состоит из одного тела вкладки, полоса
    # и приглашение живут за его пределами.
    tour_steps = []
    tour_decision = panel_tour.Decision()
    if not partial:
        tour_steps = panel_tour.build(salon, visible_keys=visible_slugs)
        tour_requested = query_params.get("tour") or None
        tour_decision = panel_tour.decide(
            steps=tour_steps,
            requested=tour_requested,
            stored_step=user.panel_tour_step,
            started=user.panel_tour_started_at is not None,
            done=user.panel_tour_done_at is not None,
            can_manage=bool(perms.get("manage_salon")),
            # «У этого уже всё работает» спрашиваем только тогда, когда это
            # может повлиять на ответ, — у кандидата на автозапуск. Проверка
            # стоит нескольких запросов, а после первого запуска ответ на неё
            # уже ничего не меняет.
            already_working=(
                await _already_working(db, salon, masters, master_ids)
                if (perms.get("manage_salon") and tour_requested is None
                    and user.panel_tour_started_at is None
                    and user.panel_tour_done_at is None)
                else False
            ),
        )
        await _save_tour_state(db, user, tour_decision)

    tour_step = tour_decision.step
    tour_on = tour_step is not None

    def _tab_href(slug: str) -> str:
        # Пока идёт знакомство, к ссылкам вкладок подклеивается tour=on: человек
        # вправе уйти в другой раздел прямо посреди шага (панель живая, решение
        # 0008, п. 8), и полоса не должна от этого исчезать.
        tail = f"&tour={panel_tour.REQUEST_ON}" if tour_on else ""
        return f"/business/dashboard?salon_id={salon.id}&tab={slug}{tail}"

    def _edit_controls(slug: str) -> str:
        """Минус и стрелки порядка у плитки. Разметку даёт сервер, а не скрипт:
        подписи для экранного диктора должны быть на русском и в одном месте.
        Пока режим редактирования выключен, кнопки скрыты через CSS — значит,
        и табом до них не дойти, возиться с tabindex не нужно."""
        name = e(panel_sections.label(slug, mode))
        out = ""
        if slug not in locked:
            out += (
                f'<button type="button" class="tab-item-minus" '
                f'aria-label="Убрать раздел «{name}» из панели" '
                f'title="Убрать из панели">{ICON_MINUS_SMALL}</button>'
            )
        # «Обзор» закреплён первым: двигать его некуда.
        if slug != "overview":
            out += (
                '<span class="tab-item-move">'
                f'<button type="button" class="tab-item-up" '
                f'aria-label="Переместить «{name}» выше" title="Выше">{ICON_ARROW_UP_TINY}</button>'
                f'<button type="button" class="tab-item-down" '
                f'aria-label="Переместить «{name}» ниже" title="Ниже">{ICON_ARROW_DOWN_TINY}</button>'
                '</span>'
            )
        return out

    def _tab_item(slug: str, *, href: bool = True) -> str:
        active_class = " active" if slug == active_tab else ""
        aria_current = ' aria-current="page"' if active_class else ""
        # Подсвечиваем ровно одну кнопку — ту, про которую идёт шаг. Это
        # единственная подсветка в туре: ни затемнения, ни выреза (решение
        # 0008, п. 3). Класс на обёртке, а не на ссылке: у неё уже есть
        # .active, и два разных состояния на одном элементе путались бы.
        tour_class = " is-tour" if (tour_step is not None and slug == tour_step.tab) else ""
        # Ссылка, а не <button onclick=window.location>: вкладка и так грузится
        # полной навигацией, но кнопкой её нельзя было открыть в новой вкладке,
        # средним кликом или без JS, и скринридер не читал её как переход.
        href_attr = f' href="{_tab_href(slug)}"' if href else ""
        locked_attr = ' data-locked="1"' if slug in locked else ""
        pinned = ' data-pinned="1"' if slug == "overview" else ""
        return (
            f'<div class="tab-item{tour_class}" data-key="{slug}" '
            f'data-label="{e(panel_sections.label(slug, mode))}"{locked_attr}{pinned}>'
            f'<a class="tab-btn{active_class}"{href_attr}{aria_current}>'
            f'{_icons[slug]} {_label_of(slug)}</a>'
            f'{_edit_controls(slug)}</div>'
        )

    nav_items_html = "".join(_tab_item(slug) for slug in visible_slugs)

    # ----- Режим редактирования панели (решение 0007, дополнение 30.09) -----
    # Разметка всегда в странице, но скрыта: скрипт только показывает её и
    # переставляет готовые плитки. Кто не вправе менять салон, тот и кнопки не
    # видит — сохранение всё равно требует manage_salon.
    gear_html = ""
    panel_edit_html = ""
    if perms.get("manage_salon"):
        gear_html = (
            '<button type="button" class="panel-edit-gear" id="panelEditBtn" '
            'aria-pressed="false" aria-controls="panelEditPanel" '
            f'title="Настроить панель">{ICON_SLIDERS}'
            '<span class="panel-edit-gear-text">Настроить панель</span></button>'
        )
        if hidden_slugs:
            chips_html = "".join(
                f'<button type="button" class="panel-edit-chip" data-key="{slug}" '
                f'aria-label="Вернуть раздел «{e(panel_sections.label(slug, mode))}» в панель">'
                f'{_icons[slug]}'
                f'<span class="panel-edit-chip-text">{e(panel_sections.label(slug, mode))}</span>'
                '<span class="panel-edit-chip-plus" aria-hidden="true">+</span>'
                '</button>'
                for slug in hidden_slugs
            )
        else:
            chips_html = '<p class="panel-edit-empty">Скрытых разделов нет — в панели все.</p>'
        # Готовая плитка для каждого скрытого раздела лежит в <template>:
        # вернуть раздел — значит достать её, а не собирать разметку в скрипте.
        # Адрес вкладки скрипт подставит сам (data-href-base у ленты): пока
        # раздел выключен, ссылки на него в странице быть не должно.
        templates_html = "".join(
            f'<template class="panel-edit-template" data-key="{slug}">'
            f'{_tab_item(slug, href=False)}</template>'
            for slug in hidden_slugs
        )
        panel_edit_html = f"""
            <div class="panel-edit" id="panelEditPanel" hidden>
                <p class="panel-edit-hint">
                    Перетащите раздел на новое место или переставьте кнопками «выше» и «ниже».
                    Минус убирает раздел из панели, плюс возвращает. «Обзор» всегда первый.
                </p>
                <h3 class="panel-edit-subtitle">Скрытые разделы</h3>
                <div class="panel-edit-chips">{chips_html}</div>
                <div class="panel-edit-actions">
                    <button type="button" class="btn-primary panel-edit-done" id="panelEditDone">
                        {ICON_CHECK_SMALL} Готово
                    </button>
                    <button type="button" class="btn-outline panel-edit-cancel" id="panelEditCancel">Отмена</button>
                    <span class="panel-edit-note" id="panelEditNote" role="status" aria-live="polite"></span>
                </div>
                {templates_html}
            </div>"""

    # Рендерим ТОЛЬКО активную вкладку
    active_body = await render_dashboard_tab(
        db, user, salon, membership, perms, masters, master_ids, active_tab, query_params,
        visible_keys=visible_slugs, tour_on=tour_on,
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
            f'<option value="{s.id}"{" selected" if s.id == salon.id else ""}>{e(s.name)}</option>'
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
    if not salon.is_active:
        # Мягкое удаление (владельцем из «Мой салон» либо модератором): панель
        # продолжает работать, а салон исчезает из каталога и записи. Раньше
        # об этом нигде не говорилось — владелец видел обычный кабинет и не
        # понимал, почему салона нет в списке.
        moderation_banner = (
            '<div style="background:#fee2e2;border:1px solid #ef4444;color:#991b1b;'
            'padding:0.9rem 1.1rem;border-radius:0.75rem;margin:1.5rem 0 0;font-size:0.9rem">'
            f'<b>{w("banner_deleted_head")}</b> {w("banner_deleted_body")}'
            '<a href="mailto:hello@rrumi.ru" style="color:#991b1b">hello@rrumi.ru</a>.</div>'
        )
    elif salon.moderation_status == SalonModerationStatus.PENDING:
        moderation_banner = (
            '<div style="background:#fef3c7;border:1px solid #f59e0b;color:#92400e;'
            'padding:0.9rem 1.1rem;border-radius:0.75rem;margin:1.5rem 0 0;font-size:0.9rem">'
            f'<b>Заявка на рассмотрении.</b> {w("banner_pending_body")}</div>'
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
            f'<b>{w("banner_approved_head")}</b> {w("banner_need_tariff_body")}'
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
            f'{ICON_SPARKLES} {w("publish_btn")}</button>'
        ) if can_publish else ''
        moderation_banner = (
            '<div style="background:#dcfce7;border:1px solid #16a34a;color:#166534;'
            'padding:0.9rem 1.1rem;border-radius:0.75rem;margin:1.5rem 0 0;font-size:0.9rem">'
            f'<b>{w("banner_approved_head")}</b> {w("banner_need_publish_body")}'
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
                f'<b>{w("banner_no_access_head")}</b> {w("banner_no_access_body")}'
                f'{_billing_link("#ef4444")}</div>'
            )
        elif salon.subscription_status == SalonSubscriptionStatus.PAST_DUE:
            moderation_banner = (
                '<div style="background:#fee2e2;border:1px solid #ef4444;color:#991b1b;'
                'padding:0.9rem 1.1rem;border-radius:0.75rem;margin:1.5rem 0 0;font-size:0.9rem">'
                f'<b>Не удалось списать оплату.</b> {w("banner_past_due_body")}'
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
                f'(до {deadline}). {w("banner_trial_tail")}'
                f'{_billing_link("#f59e0b")}</div>'
            )

    publish_gate_modal_html = ""
    if show_publish_gate_modal:
        publish_gate_modal_html = f"""
        <div class="publish-gate-modal-overlay" id="publishGateModal" data-salon-id="{salon.id}">
            <div class="publish-gate-modal-box">
                <button type="button" class="publish-gate-modal-close" id="publishGateModalClose">&times;</button>
                <div class="publish-gate-icon">💳</div>
                <h2>{w("publish_gate_title")}</h2>
                <p>{w("publish_gate_body")}</p>
                <a href="/business/dashboard?salon_id={salon.id}&tab=billing" class="btn-primary">
                    {ICON_SPARKLES} Выбрать тариф
                </a>
            </div>
        </div>"""

    # Полоса знакомства и приглашение — ровно одно из двух: полоса уже ведёт по
    # шагам, звать в неё отдельной строкой было бы повтором.
    tour_bar_html = ""
    tour_invite_html = ""
    if tour_step is not None:
        tour_bar_html = render_tour_bar(
            salon_id=salon.id, steps=tour_steps, step=tour_step, current_tab=active_tab,
        )
    elif tour_decision.invite_step is not None:
        tour_invite_html = render_tour_invite(
            salon_id=salon.id, steps=tour_steps, step=tour_decision.invite_step,
        )

    # Полоса закреплена снизу, поэтому странице нужен запас места: иначе она
    # накрыла бы кнопки сохранения в последнем блоке раздела.
    body_class = "panel-tour-open" if tour_bar_html else ""

    # Подзаголовок шапки: в соло имя человека — это и есть имя в ленте, и
    # приписка «Салон «…»» перед ним звучит как чужая вывеска.
    where = salon.address.split(',')[0] if salon.address else 'Адрес не указан'
    header_subtitle = (
        f'{e(salon.name)} • {where}' if panel_sections.is_solo(salon)
        else f'Салон «{e(salon.name)}» • {where}'
    )

    header_html = f"""
    <div class="dashboard-header">
        <div class="dashboard-header-inner">
            <div class="header-title">
                <h1>{w("header_title")}</h1>
                <p>{header_subtitle}</p>
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
    <title>Бизнес-панель — {e(salon.name)} — руми</title>
    {get_base_styles()}
    {render_yandex_maps_script()}
</head>
<body class="{body_class}">
    {render_header("business")}
    {render_sidebar("business_dashboard", user)}
    <main style="margin-right:0;padding-top:0">
        {header_html}
        <div class="section-container" id="salon-status" style="padding-top: 0;">{moderation_banner}</div>
        <div class="section-container" style="padding-top: 1.5rem;">
            <div class="tab-nav-row">
                <div class="tab-nav" id="panelNav" data-salon-id="{salon.id}"
                     data-href-base="/business/dashboard?salon_id={salon.id}&tab=">
                    {nav_items_html}
                </div>
                {gear_html}
            </div>
            {panel_edit_html}
            {tour_invite_html}
            {tabs_body_html}
        </div>
    </main>
    {render_footer(user)}
    {publish_gate_modal_html}
    {tour_bar_html}
</body>
</html>"""

    return html