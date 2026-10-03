# app/web/pages/business/tabs/overview.py

from app.web.components.escaping import e
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta
from app.models.models import Booking, BookingStatus, User, Review
from app.models.models import SalonPanelMode
from app.services import panel_guide
from app.web.components.booking_link import render_booking_link_block
from app.web.components.hint import hint as _hint
from app.web.components.icons import (
    ICON_USERS_SMALL,
    ICON_CALENDAR_DAYS_SMALL,
    ICON_TRENDING_UP,
    ICON_STAR_FILLED,
    ICON_ARROW_UP_RIGHT,
    ICON_USER_CHECK,
    ICON_CLOCK,
    ICON_X,
    ICON_RUBLE_SIGN,
    ICON_CREDIT_CARD_SMALL,
    ICON_CHECK,
    ICON_CIRCLE_CHECK,
    ICON_CIRCLE_X,
    ICON_ALERT_TRIANGLE,
    ICON_HEART,
    ICON_ARROW_RIGHT,
    ICON_CHEVRON_DOWN,
)


def _tab_url(salon_id: int, target: str) -> str:
    """Адрес действия из строки «что мешает». Якорь (#…) ведёт на ту же
    страницу — плашка статуса салона в шапке панели: кнопка «Опубликовать»
    живёт только там, и дублировать её здесь нельзя (обработчик висит на id)."""
    if target.startswith("#"):
        return target
    return f"/business/dashboard?salon_id={salon_id}&tab={target}"


def _action_html(salon_id: int, action: str, target: str) -> str:
    """Подпись действия ссылкой в нужный раздел. Без адреса подписи тоже нет:
    кнопка, которая никуда не ведёт, хуже её отсутствия."""
    if not target or not action:
        return ""
    return (
        f'<a class="readiness-action" href="{_tab_url(salon_id, target)}">'
        f'{action} {ICON_ARROW_RIGHT}</a>'
    )


def _row(text: str, action: str = "", css: str = "") -> str:
    return (
        f'<li class="readiness-row {css}">'
        f'<span class="readiness-text">{text}</span>{action}</li>'
    )


def _group(title: str, lead: str, rows: str, css: str = "") -> str:
    if not rows:
        return ""
    lead_html = f'<p class="growth-group-lead">{lead}</p>' if lead else ""
    return f"""
        <div class="growth-group {css}">
            <h3 class="growth-group-title">{title}</h3>
            {lead_html}
            <ul class="readiness-list">{rows}</ul>
        </div>"""


# Условия группы 1, сведённые в «ворота». Нужны линии прогресса: сервис
# booking_readiness отдаёт только НЕЗАКРЫТЫЕ причины, а «сделано N из M» просит
# ещё и знаменатель. Пересчитывать условия второй раз здесь нельзя — две копии
# правил разъедутся при первой правке, — поэтому считаем по ключам причин.
#
# Почему ворота, а не одиннадцать причин по штуке. В booking_readiness причины
# внутри ворот стоят через elif, то есть ОДНО условие показывается двумя разными
# фразами, смотря что именно не так: нет мастера → «нет карточки мастера», есть
# мастер без услуг → «ни одной услуги». Считая их за два пункта, мы бы получили
# прыжок назад: человек заводит карточку мастера, закрывает одну причину — и
# тут же открывается вторая, прогресс стоит на месте, а «всего» растёт. С
# воротами «всего» не меняется вовсе: оно равно числу ворот, одному и тому же у
# любого салона, и прогресс двигается только когда условие реально закрыто.
#
# «Сделано» = ворота, в которых ни одна причина не открыта. Это честно: ворота
# закрыты — значит состояние верное, независимо от того, кто его таким сделал
# (запись по ссылке включена по умолчанию, и это всё равно работающее условие).
_VISIBLE_GATES = (
    ("exists", ("salon_deleted",)),
    ("moderation", ("moderation_pending", "moderation_rejected")),
    ("tariff", ("no_tariff",)),
    ("published", ("not_published",)),
    ("masters", ("no_master", "no_services")),
    ("hours", ("no_salon_hours", "no_workdays")),
    ("catalog", ("hidden",)),
    ("link", ("guest_booking_off",)),
)

#: Причина, после которой evaluate() обрывается и больше ничего не проверяет.
_SHORT_CIRCUIT = "salon_deleted"


def _path_progress(readiness, checklist):
    """«сделано N из M» по ПРИМЕНИМЫМ пунктам обеих групп (решение 0010,
    дополнение 03.10.2026, п. 2).

    Группа 1 — ворота выше: M всегда одно и то же, N — закрытые.
    Группа 2 — пункты как есть: growth_checklist уже выбросил неприменимые
    (акцию без услуг, вечерние окна без часов приёма), и считать их здесь было
    бы прямым обманом — человек увидел бы дела, которых ему не показывают.

    «Всего» группы 2 всё же может вырасти — когда появляется первая услуга,
    акция и вечерние окна становятся применимы. Это рост С ПРИЧИНОЙ: путь
    действительно стал длиннее, и обе новые строки человек видит рядом с
    полосой. Прыжков БЕЗ причины — от того, что мы что-то скрыли, — здесь нет.

    Удалённый салон — особый случай: evaluate() обрывается на первой причине и
    остальных условий не проверяет вовсе. Записать их в «сделано» значило бы
    отчитаться за проверки, которых не было, поэтому группа 1 сжимается до
    единственных известных ворот: 0 из 1.
    """
    open_keys = {i.key for i in readiness.issues}
    if _SHORT_CIRCUIT in open_keys:
        done, total = 0, 1
    else:
        total = len(_VISIBLE_GATES)
        done = sum(
            1 for _gate, keys in _VISIBLE_GATES
            if not open_keys.intersection(keys)
        )

    if checklist is not None:
        total += len(checklist.items)
        done += checklist.done_count
    return done, total


def _render_progress(done: int, total: int) -> str:
    """Полоса и подпись под ней.

    Подпись — не украшение полосы, а её содержание: полоса без подписи читается
    только глазами и только у того, кто различает цвета. Поэтому role у
    полосы, а текст стоит рядом обычным абзацем.
    """
    note = panel_guide.check_progress(done, total)
    pct = round(done * 100 / total) if total else 0
    return f"""
        <div class="growth-progress">
            <div class="growth-progress-track" role="progressbar"
                 aria-valuemin="0" aria-valuemax="{total}" aria-valuenow="{done}"
                 aria-valuetext="{note}">
                <span class="growth-progress-fill" style="width:{pct}%"></span>
            </div>
            <p class="growth-progress-note">{note}</p>
        </div>"""


def _render_path(salon, readiness, checklist, next_links, solo: bool) -> str:
    """«Путь к первому клиенту» — один блок на три группы (решение 0010).

    До захода 6 здесь было два блока: «Можно ли к вам записаться» и текстовый
    гайд в «Инструкции». Списки у них пересекались, и через месяц правок они
    начали говорить об одном разными словами — та же болезнь, от которой лечили
    заходы 3 и 5.

    Вердикт сверху — ТОТ ЖЕ, что был у блока готовности: те же слова, тот же
    класс состояния и, значит, тот же цвет (решение 0010, п. 1). Растворять
    «записаться нельзя» в бодром «выполнено 4 из 11» нельзя: это единственная
    строка в панели, из которой человек узнаёт, что заявок не будет.

    Что считается — booking_readiness (группа 1) и growth_checklist (группа 2);
    тексты — panel_guide. Здесь только показ, и пользовательских данных в
    строках нет (все тексты — литералы реестра), поэтому экранировать нечего:
    если в строку когда-нибудь попадёт имя салона или причина отказа модерации,
    её придётся пропустить через e().
    """
    who = "к вам" if solo else "в ваш салон"
    if not readiness.issues:
        state, mark = "ok", ICON_CIRCLE_CHECK
        verdict = f"Записаться {who} можно"
        sub = "Ссылка, QR и каталог работают — клиент выберет услугу и время сам."
    elif readiness.can_book:
        # Блокировок нет, но один из двух путей записи закрыт.
        state, mark = "warn", ICON_ALERT_TRIANGLE
        verdict = f"Записаться {who} можно, но не всеми способами"
        sub = ""
    else:
        state, mark = "bad", ICON_CIRCLE_X
        verdict = f"Записаться {who} сейчас нельзя"
        sub = "Пока это не исправлено, заявок не будет — даже по ссылке."

    groups = dict(
        (key, (title, lead)) for key, title, lead in panel_guide.check_groups()
    )

    # ── Группа 1: то, без чего записаться нельзя (booking_readiness как есть) ──
    rows = "".join(
        _row(
            issue.text,
            _action_html(salon.id, issue.action, issue.target),
            f'readiness-row-{"bad" if issue.blocking else "warn"}',
        )
        for issue in readiness.issues
    )
    if not rows:
        # Группа не исчезает: исчезающий заголовок дёргал бы разметку при
        # каждом исправлении, а пустой — обещал бы содержимое, которого нет.
        rows = _row(panel_guide.CHECK_VISIBLE_CLEAR, css="growth-done")
    title, lead = groups[panel_guide.CHECK_GROUP_VISIBLE]
    html = _group(title, lead, rows)

    # ── Группа 2: то, из-за чего выбирают вас ──
    if checklist is not None:
        rows = "".join(
            _row(item.text, _action_html(salon.id, item.action, item.target),
                 "growth-row")
            for item in checklist.pending
        )
        # Выполненные схлопываются в одну строку (решение 0010, п. 5):
        # шесть галочек подряд — это обои, а не список дел.
        if checklist.done_count:
            rows += _row(
                f"{panel_guide.CHECK_DONE_PREFIX}: {checklist.done_count}",
                css="growth-done",
            )
        title, lead = groups[panel_guide.CHECK_GROUP_CHOSEN]
        html += _group(title, lead, rows)

    # ── Группа 3: появляется, только когда в первых двух дел не осталось ──
    if next_links:
        rows = "".join(
            _row(phrase, _action_html(salon.id, label, key), "growth-next")
            for key, label, phrase in next_links
        )
        title, lead = groups[panel_guide.CHECK_GROUP_NEXT]
        html += _group(title, lead, rows, "growth-group-next")

    sub_html = f'<p class="readiness-sub">{sub}</p>' if sub else ""

    # ── Шапка: вердикт, свёртка и линия прогресса ──
    # Шапка видна в ЛЮБОМ состоянии блока, и вердикт в ней один и тот же.
    # Жёсткое условие решения 0010 (п. 1 и п. 4 дополнения): свёрнутый блок —
    # не способ спрятать «записаться нельзя». Поэтому вердикт, его класс
    # состояния (значит, цвет) и приписка под ним остаются снаружи свёртки, а
    # внутрь уходят только группы.
    done, total = _path_progress(readiness, checklist)

    # По умолчанию блок развёрнут, пока есть незакрытые дела, и свёрнут, когда
    # дел не осталось: там уже только «куда смотреть дальше» (решение 0010,
    # дополнение, п. 3). Решает это сервер, а не скрипт, — иначе человек,
    # у которого всё закрыто, успевал бы увидеть вспышку развёрнутого списка.
    pending = bool(readiness.issues) or bool(checklist and checklist.pending)
    collapsed = " is-collapsed" if not pending else ""

    # Класс is-collapsible не ставится здесь намеренно: его добавляет скрипт.
    # Правила свёртки в CSS висят только на нём, поэтому без JS блок остаётся
    # развёрнутым и читаемым целиком — серверный HTML у нас основа, а не
    # прогрессивное улучшение поверх пустой страницы. По той же причине кнопка
    # приходит с hidden (мёртвый орган управления хуже его отсутствия) и
    # aria-expanded="true": без скрипта блок действительно развёрнут.
    body_id = f"growth-body-{salon.id}"
    return f"""
    <section class="readiness readiness-{state} growth{collapsed}"
             aria-label="{panel_guide.CHECKLIST_TITLE}"
             data-growth-path="{salon.id}">
        <p class="growth-kicker">{panel_guide.CHECKLIST_TITLE}</p>
        <p class="readiness-verdict"><span class="readiness-mark">{mark}</span>{verdict}</p>
        {sub_html}
        <button class="growth-toggle" type="button" hidden
                aria-expanded="true" aria-controls="{body_id}">
            <span class="growth-toggle-label">{panel_guide.CHECK_IMPROVE}</span>
            <span class="growth-toggle-chevron">{ICON_CHEVRON_DOWN}</span>
        </button>
        {_render_progress(done, total)}
        <div class="growth-body" id="{body_id}">
            <div class="growth-body-inner">{html}</div>
        </div>
    </section>
    """


def _render_models_invite(salon_id: int) -> str:
    """Приглашение в раздел «Модели» — его за 25 дней открыли один раз, и это
    при том, что он включён в обоих режимах (решение 0007, п. 2).

    Каждое утверждение здесь сверено с app/web/pages/business/tabs/promo_models.py
    и app/services/model_matching_service.py: публикуется поиск на КОНКРЕТНУЮ
    услугу со своей ценой и длительностью, обычным клиентам она не видна
    (is_model_practice), квота закрывает набор, а откликнувшаяся модель сама
    выбирает свободное окно в расписании мастера — отдельного шага «оффер» нет.
    Ничего сверх этого обещать нельзя.
    """
    return f"""
    <section class="models-invite" aria-label="Раздел «Модели»">
        <span class="models-invite-mark">{ICON_HEART}</span>
        <div class="models-invite-body">
            <h3 class="models-invite-title">Ищете моделей на отработку?</h3>
            <p class="models-invite-text">
                Опубликуйте поиск на отдельную услугу — со своей ценой, длительностью,
                желаемой датой и числом моделей, которое нужно набрать. Обычным клиентам
                такая услуга не показывается. Кто откликнулся, сам выбирает свободное
                окно в вашем расписании, а когда набор закончен, поиск закрывается.
            </p>
            <a class="models-invite-link" href="/business/dashboard?salon_id={salon_id}&tab=models">
                Открыть «Модели» {ICON_ARROW_RIGHT}</a>
        </div>
    </section>
    """


async def render_overview_tab(
    db: AsyncSession,
    salon,
    masters,
    master_ids,
    services_count,
    promotions,
    today_bookings,
    today_bookings_list,
    revenue_data,
    prev_revenue_data,
    total_revenue,
    revenue_diff,
    revenue_trend,
    revenue_color,
    week_operations,
    days,
    *,
    solo: bool = False,
    readiness=None,
    checklist=None,
    next_links=(),
    show_booking_link: bool = False,
    show_models_invite: bool = False,
    has_any_booking: bool = True,
    extra_html: str = "",
) -> str:
    """Вкладка «Обзор» — главный экран панели.

    Собирается из блоков, и порядок у режимов разный (решение 0007, п. 6):

      соло: путь к первому клиенту → ссылка и QR → сегодня → «Модели» →
      выручка;
      команда: привычные счётчики, график и «сегодня» → путь к первому клиенту
      → ссылка и QR.

    Место блока у режимов разное намеренно (решение 0010, «место блока»): в
    соло первый экран занимать больше нечем, а салону с командой есть чем —
    поэтому там путь встаёт НИЖЕ счётчиков и графика. Исчезать блоку нельзя ни
    в одном состоянии: он успел стать местом, куда человек смотрит, и пустота
    на его месте читается как поломка.

    Соло-мастеру деньги показываем, только когда записи вообще существуют:
    пустой график и четыре нуля — не информация, а шум на первом экране.

    Новые аргументы — именованные и со значениями по умолчанию: тот же рендер
    зовёт панель мастера (master_dashboard.py), где ни блока готовности, ни
    ссылки быть не должно — там человек наёмный, а разделы, куда ведут
    действия, ему не принадлежат.

      solo             — режим салона «работаю один» (panel_sections.is_solo);
      readiness        — Readiness из services/booking_readiness.py или None,
                         если блок «путь к первому клиенту» показывать не нужно
                         (наёмный мастер, участник без manage_salon);
      checklist        — Checklist из services/growth_checklist.py: группа 2
                         «чтобы выбирали вас». None — группы не будет: у
                         удалённого профиля «обложка не выбрана» это шум;
      next_links       — группа 3 «куда смотреть дальше», готовым списком
                         (ключ, название, фраза). Пустой — группы нет: она
                         появляется, только когда дел не осталось;
      show_booking_link — рисовать ли ссылку и QR;
      show_models_invite — приглашать ли в «Модели». Раздел владелец может
                         выключить в самой панели, и звать в выключенный
                         раздел нельзя: ссылка вернула бы человека в «Обзор»;
      has_any_booking  — есть ли у салона хоть одна запись за всё время;
      extra_html       — что дописать в конец вкладки. Нужен панели мастера:
                         она добавляет свои карточки и раньше вклеивала их
                         поиском подстроки «</div>\n    </div>» в готовой
                         разметке. Любая перестановка блоков здесь молча
                         уводила их в середину экрана.
    """
    # Подписи — из реестра: соло-мастеру панель говорит «ваши клиенты», а не
    # «клиенты салона» (решение 0009, п. 6).
    w = panel_guide.words_for(
        SalonPanelMode.SOLO if solo else SalonPanelMode.TEAM
    )
    
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)

    # --- Количество уникальных клиентов салона (всего и неделю назад) ---
    clients_count = 0
    clients_count_prev = 0
    if master_ids:
        clients_result = await db.execute(
            select(func.count(func.distinct(Booking.client_id)))
            .where(Booking.master_id.in_(master_ids))
        )
        clients_count = clients_result.scalar() or 0

        clients_prev_result = await db.execute(
            select(func.count(func.distinct(Booking.client_id)))
            .where(Booking.master_id.in_(master_ids), Booking.start_time < week_ago)
        )
        clients_count_prev = clients_prev_result.scalar() or 0

    # --- Записи: сегодня vs вчера ---
    bookings_yesterday = 0
    if master_ids:
        by_result = await db.execute(
            select(func.count(Booking.id))
            .where(Booking.master_id.in_(master_ids), Booking.start_time >= yesterday, Booking.start_time < today)
        )
        bookings_yesterday = by_result.scalar() or 0

    # --- Рейтинг: текущий vs средний по отзывам недельной давности ---
    rating_prev_result = await db.execute(
        select(func.avg(Review.rating)).where(Review.salon_id == salon.id, Review.created_at < week_ago)
    )
    rating_prev_raw = rating_prev_result.scalar()
    rating_prev = float(rating_prev_raw) if rating_prev_raw is not None else None

    def pct_trend(current: float, previous: float) -> tuple[str, str]:
        """Текст и css-класс (up/down/flat) для процентного изменения current относительно previous."""
        # Базы для процента нет: и «0%», и «+100%» тут вымышленные. Пустой текст
        # — чип не рисуется вовсе, вместо шума на всех плитках нового салона.
        if previous <= 0:
            return "", "flat"
        pct = (current - previous) / previous * 100
        if pct > 0.05:
            return f"+{pct:.0f}%", "up"
        if pct < -0.05:
            return f"{pct:.0f}%", "down"
        return "0%", "flat"

    def trend_badge(text: str, css_class: str) -> str:
        if not text:
            return ""
        if css_class == "up":
            icon = ICON_ARROW_UP_RIGHT
        elif css_class == "down":
            icon = f'<span style="display:inline-flex;transform:rotate(90deg)">{ICON_ARROW_UP_RIGHT}</span>'
        else:
            icon = ""
        return f'<span class="stat-trend {css_class}">{icon}{text}</span>'

    clients_trend = trend_badge(*pct_trend(clients_count, clients_count_prev))
    records_trend = trend_badge(*pct_trend(today_bookings, bookings_yesterday))
    revenue_trend_pct = trend_badge(*pct_trend(total_revenue, sum(prev_revenue_data.values())))

    current_rating = salon.rating or 0.0
    # Чип рисуем только когда оценка реально сдвинулась. Раньше здесь стояли «—»
    # (сравнивать не с чем) и «0.0» (не менялась) — рядом со значением «5.0»
    # такой чип читается как вторая оценка, а не как отсутствие изменений.
    rating_trend = ""
    if rating_prev is not None:
        rating_diff = current_rating - rating_prev
        if rating_diff > 0.05:
            rating_trend = trend_badge(f"+{rating_diff:.1f}", "up")
        elif rating_diff < -0.05:
            rating_trend = trend_badge(f"{rating_diff:.1f}", "down")

    # --- Данные для JS (аккордеон) ---
    week_ops_serialized = []
    total_bookings_week = 0
    for i in range(7):
        day_ops = []
        for booking, service, client in week_operations[i]:
            day_ops.append({
                "id": booking.id,
                "start_time": booking.start_time.isoformat(),
                "final_price": booking.final_price,
                "status": booking.status.value,
                "payment_method": getattr(booking, "payment_method", "Карта"),
                "service": {"name": service.name, "price": service.price},
                "client": {"full_name": client.full_name, "phone": client.phone}
            })
        week_ops_serialized.append(day_ops)
        total_bookings_week += len(day_ops)
    
    week_operations_json = json.dumps(week_ops_serialized, ensure_ascii=False)
    days_json = json.dumps(days, ensure_ascii=False)
    
    # Средний чек за неделю
    avg_check = total_revenue // max(total_bookings_week, 1) if total_bookings_week > 0 else 0
    
    # --- 1. КАРТОЧКИ СТАТИСТИКИ ---
    stats_cards = f"""
    <div class="stats-grid-4">
        <div class="stat-card">
            <div class="stat-card-header">
                <div class="stat-icon">{ICON_USERS_SMALL}</div>
                {clients_trend}
            </div>
            <p class="stat-value">{clients_count}</p>
            <p class="stat-label">Клиентов {_hint(w("hint_clients"))}</p>
        </div>

        <div class="stat-card">
            <div class="stat-card-header">
                <div class="stat-icon">{ICON_CALENDAR_DAYS_SMALL}</div>
                {records_trend}
            </div>
            <p class="stat-value">{today_bookings}</p>
            <p class="stat-label">Записей {_hint("Записи на сегодня (кроме отменённых). Процент — по сравнению со вчера.")}</p>
        </div>

        <div class="stat-card">
            <div class="stat-card-header">
                <div class="stat-icon">{ICON_TRENDING_UP}</div>
                {revenue_trend_pct}
            </div>
            <p class="stat-value">{f"{total_revenue:,}".replace(",", " ")} ₽</p>
            <p class="stat-label">Выручка {_hint("Сумма подтверждённых и завершённых записей за текущую неделю (Пн—Вс). Процент — по сравнению с прошлой неделей.")}</p>
        </div>

        <div class="stat-card">
            <div class="stat-card-header">
                <div class="stat-icon">{ICON_STAR_FILLED}</div>
                {rating_trend}
            </div>
            <p class="stat-value">{current_rating:.1f}</p>
            <p class="stat-label">Рейтинг {_hint(w("hint_rating"))}</p>
        </div>
    </div>
    """

    # --- 2. ВЫРУЧКА ЗА НЕДЕЛЮ (график с аккордеоном) ---
    max_revenue = max(max(revenue_data.values()) if revenue_data else 1, 1)
    chart_height = 80
    revenue_bars = ""
    for i in range(7):
        height = int(revenue_data[i] / max_revenue * chart_height) if max_revenue > 0 else 5
        # Пустой день — тонкая нейтральная засечка, а не зелёный столбик на 8px:
        # при нулевой неделе график рисовал семь зелёных полосок, и это читалось
        # как «выручка есть», хотя над каждой стояло «0 ₽».
        if revenue_data[i] > 0:
            height = max(height, 8)
            bar_bg = ("background: linear-gradient(to top, var(--color-success), "
                      "color-mix(in srgb, var(--color-success) 80%, transparent));")
        else:
            height = 2
            bar_bg = "background: var(--color-border);"
        rev_val = f"{revenue_data[i]}".replace(",", " ")
        revenue_bars += f"""
        <div class="chart-column" data-day-index="{i}" style="cursor:pointer">
            <div class="chart-value">{rev_val} ₽</div>
            <div class="chart-fill" style="height:{height}px; {bar_bg}"></div>
            <span class="chart-label">{days[i]}</span>
        </div>"""

    # Контейнер для аккордеона (детали дня)
    accordion_html = f"""
    <div class="day-accordion" id="dayAccordion" style="display:none;">
        <div class="day-accordion-header">
            <h4 id="accordionDayTitle">Операции за день</h4>
            <span id="accordionDaySummary" class="text-muted"></span>
            <button class="accordion-close">{ICON_X}</button>
        </div>
        <div id="accordionDayOperations" class="day-accordion-body"></div>
    </div>
    """

    revenue_html = f"""
    <div class="chart-wrapper">
        <div class="chart-header">
            <h3>{ICON_RUBLE_SIGN} Выручка за неделю</h3>
            <span class="chart-total">Общая: {total_revenue:,} ₽</span>
        </div>
        <div class="chart-bar" id="overviewChartBar">{revenue_bars}</div>
        <div class="kpi-row">
            <span><span class="kpi-label">Средний чек: </span><strong>{avg_check:,} ₽</strong></span>
            <span><span class="kpi-label">Динамика: </span><strong style="color:{revenue_color}">{revenue_trend} {abs(revenue_diff):,} ₽</strong></span>
        </div>
        <p style="font-size:0.7rem;color:var(--color-muted);text-align:center;margin-top:0.75rem">Нажмите на столбец, чтобы увидеть детали дня</p>
        
        {accordion_html}
    </div>
    """

    # --- 3. СЕГОДНЯ ---
    today_items = ""
    if today_bookings_list:
        for booking, service, client in today_bookings_list:
            status_label = f"{ICON_CHECK} Оплачено" if booking.status == BookingStatus.COMPLETED else "○ Ожидание"
            status_class = "status-paid" if booking.status == BookingStatus.COMPLETED else "status-waiting"
            initials = "".join([part[0].upper() for part in client.full_name.split()]) if client.full_name else "К"
            price_str = f"{booking.final_price or service.price:,}".replace(",", " ")
            time_str = booking.start_time.strftime("%H:%M")
            service_name = service.name
            today_items += f"""
            <div class="booking-item">
                <div class="avatar">{initials}</div>
                <div class="info">
                    <div class="name">{e(client.full_name or client.phone)}</div>
                    <div class="desc">
                        {ICON_CLOCK} {time_str} • {e(service_name)}
                    </div>
                </div>
                <div class="price">{price_str} ₽</div>
                <span class="status {status_class}">{status_label}</span>
            </div>
            """
    else:
        # Пустая таблица ничего не сообщает. Про ссылку говорим только там, где
        # она тут же на экране, и без «выше/ниже»: порядок блоков у режимов разный.
        empty_text = (
            "Записей на сегодня нет — раздайте клиентам ссылку для записи."
            if show_booking_link and solo else "Записей на сегодня нет."
        )
        today_items = (
            f'<p class="today-empty">{empty_text}</p>'
        )

    today_html = f"""
    <div class="card">
        <div class="chart-header">
            <h3 style="display:flex;align-items:center;gap:0.5rem">
                <span style="display:inline-flex;align-items:center;color:var(--color-primary)">{ICON_USER_CHECK}</span>
                Сегодня
            </h3>
            <span class="chart-total">{len(today_bookings_list)} клиентов</span>
        </div>
        <div class="space-y-3">
            {today_items}
        </div>
    </div>
    """

    # --- 4. Собираем всё ---
    # Путь к первому клиенту показываем всегда, в обоих режимах и во всех
    # состояниях (решение 0010, п. 4). Прежнее «команде — только когда есть что
    # исправлять» больше не действует: блок перестал быть предупреждением и
    # стал местом, где написано, что делать дальше. Нет его только у того, кому
    # нечего в нём нажать, — см. readiness=None.
    path_html = ""
    if readiness is not None:
        path_html = _render_path(salon, readiness, checklist, next_links, solo)

    booking_link_html = ""
    if show_booking_link:
        # enabled — ровно про тумблер «запись без регистрации», потому что
        # приписка под заголовком объясняет именно его. Передавать сюда
        # readiness.link_works нельзя: он False и когда салон не опубликован,
        # и человек прочитал бы, что выключил тумблер, которого не трогал.
        # Остальные причины уже перечислены блоком готовности выше — второй
        # раз, да ещё и неверно, их называть незачем.
        booking_link_html = render_booking_link_block(
            salon.id, enabled=bool(salon.guest_booking_enabled),
            qr_alt=w("qr_alt"), solo=solo,
        )

    if solo:
        # Деньги — последним и только когда записи существуют. Пока их нет,
        # счётчики и график показывали четыре нуля и семь засечек.
        money_html = f"""
        {stats_cards}
        {revenue_html}
        """ if has_any_booking else ""
        body = f"""
        {path_html}
        {booking_link_html}
        {today_html}
        {_render_models_invite(salon.id) if show_models_invite else ""}
        {money_html}
        """
    else:
        body = f"""
        {stats_cards}
        <div class="overview-grid-2-1">
            {revenue_html}
            {today_html}
        </div>
        {path_html}
        {booking_link_html}
        {_render_models_invite(salon.id) if show_models_invite else ""}
        """

    return f"""
    <div id="tab-overview" class="tab-content">
        {body}
        {extra_html}
    </div>

    <script>
        window.weekOperations = {week_operations_json};
        window.days = {days_json};
    </script>
    """