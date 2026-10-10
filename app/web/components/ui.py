# app/web/components/ui.py
"""Базовый набор элементов интерфейса: кнопка, поле, карточка, плашка-статус,
пустое состояние.

Зачем хелперы, а не «просто классы»: разметка у нас живёт в f-строках внутри
.py, и без общей функции каждая страница пишет свою кнопку. За год так
накопилось двадцать похожих — и в ревизии контраста пришлось обходить каждую
отдельно. Здесь кнопка одна, и правка состояния фокуса доезжает всюду разом.

Стили — static/src/css/ui.css, класс-префикс r-. Это ДОБАВЛЕННЫЙ слой: старые
.btn-primary/.card/.empty-state остаются, страницы переходят в свои заходы
(решение 0011, пункт 6).

Всё, что приходит от пользователя, проходит через e(): шаблонизатора с
автоэкранированием у нас нет.
"""
import hashlib
from typing import Literal

from app.web.components.escaping import e
from app.web.components.icons import ICON_STAR_FILLED

ButtonKind = Literal["primary", "secondary", "danger"]
StatusTone = Literal["neutral", "accent", "success", "warning", "danger"]


def _attrs(pairs: dict) -> str:
    """Словарь → строка атрибутов. None и пустые значения пропускаются,
    чтобы не сыпать в разметку id="" и data-x=""."""
    out = []
    for k, v in pairs.items():
        if v is None or v == "":
            continue
        if v is True:
            out.append(k)
        else:
            out.append(f'{k}="{e(v)}"')
    return (" " + " ".join(out)) if out else ""


def button(
    label: str,
    *,
    kind: ButtonKind = "primary",
    href: str = "",
    type_: str = "button",
    form: str = "",
    element_id: str = "",
    block: bool = False,
    small: bool = False,
    disabled: bool = False,
    loading: bool = False,
    icon: str = "",
    classes: str = "",
    data: dict | None = None,
    aria_label: str = "",
    external: bool = False,
) -> str:
    """Кнопка. С href — ссылка, выглядящая и ведущая себя как кнопка.

    ``external`` — ссылка уходит на чужой сайт (бот в мессенджере): открывается
    в новой вкладке, rel=noopener не даёт ей доступа к нашему окну.

    Состояния «наведение», «фокус», «нажатие» рисует CSS; здесь задаются
    только те, что зависят от данных: выключена и загружается.

    loading не просто красит кнопку: подпись остаётся в потоке (её прячет
    visibility), иначе кнопка схлопывается по ширине и уезжает из-под пальца
    ровно в тот момент, когда по ней попали.
    """
    cls = ["r-btn", f"r-btn--{kind}"]
    if block:
        cls.append("r-btn--block")
    if small:
        cls.append("r-btn--sm")
    if loading:
        cls.append("is-loading")
    if classes:
        cls.append(classes)

    icon_html = f'<span class="r-btn__icon" aria-hidden="true">{icon}</span>' if icon else ""
    inner = (
        f'{icon_html}<span class="r-btn__label">{e(label)}</span>'
        f'<span class="r-btn__spinner" aria-hidden="true"></span>'
    )

    common = {
        "class": " ".join(cls),
        "id": element_id,
        "aria-label": aria_label,
    }
    for k, v in (data or {}).items():
        common[f"data-{k}"] = v

    if href:
        # У <a> нет disabled. aria-disabled сообщает состояние скринридеру,
        # tabindex=-1 убирает из обхода с клавиатуры, а клик глушит CSS
        # (pointer-events на .is-loading и курсор not-allowed на выключенной).
        link = dict(common)
        link["href"] = "#" if disabled else href
        if external:
            link["target"] = "_blank"
            link["rel"] = "noopener"
        if disabled:
            link["aria-disabled"] = "true"
            link["tabindex"] = "-1"
        return f"<a{_attrs(link)}>{inner}</a>"

    btn = dict(common)
    btn["type"] = type_
    # form= связывает кнопку с формой, лежащей в другом месте разметки: на
    # /salons поиск стоит в шапке страницы, а сама форма фильтров — ниже.
    # Без атрибута Enter в поле срабатывает, а клик по кнопке — нет.
    btn["form"] = form
    if disabled:
        btn["disabled"] = True
    if loading:
        btn["aria-busy"] = "true"
    return f"<button{_attrs(btn)}>{inner}</button>"


def field(
    label: str,
    *,
    name: str = "",
    element_id: str = "",
    type_: str = "text",
    value: str = "",
    placeholder: str = "",
    hint: str = "",
    error: str = "",
    required: bool = False,
    autocomplete: str = "",
    inputmode: str = "",
    classes: str = "",
    input_classes: str = "",
    data: dict | None = None,
    error_id: str = "",
) -> str:
    """Поле ввода с подписью, подсказкой и местом под ошибку.

    Место под ошибку есть всегда (min-height в CSS), даже когда ошибки нет:
    иначе её появление сдвигает кнопку «Записаться» вниз ровно в тот момент,
    когда человек в неё целится.

    Подсказка и ошибка связаны с полем через aria-describedby — иначе
    скринридер прочитает подпись и замолчит, а причина отказа останется
    видна только глазами.
    """
    # id нужен подписи (for=) и связке aria-describedby. Если вызывающий его
    # не дал, берём имя поля, а в последнюю очередь — хэш подписи: подпись
    # русская, а кириллический id хоть и валиден, но ломает querySelector('#…')
    # без экранирования и читается в разметке как опечатка.
    fid = element_id or name or ("f-" + hashlib.md5(label.encode("utf-8")).hexdigest()[:8])
    hint_id = f"{fid}-hint"
    err_id = error_id or f"{fid}-error"

    described = []
    if hint:
        described.append(hint_id)
    described.append(err_id)

    wrap_cls = ["r-field"]
    if error:
        wrap_cls.append("is-invalid")
    if classes:
        wrap_cls.append(classes)

    inp = {
        "class": ("r-input " + input_classes).strip(),
        "id": fid,
        "name": name or None,
        "type": type_,
        "value": value or None,
        "placeholder": placeholder or None,
        "autocomplete": autocomplete or None,
        "inputmode": inputmode or None,
        "aria-describedby": " ".join(described),
    }
    if required:
        inp["required"] = True
        inp["aria-required"] = "true"
    if error:
        inp["aria-invalid"] = "true"
    for k, v in (data or {}).items():
        inp[f"data-{k}"] = v

    req_mark = '<span class="r-field__req" aria-hidden="true">*</span>' if required else ""
    hint_html = f'<p class="r-field__hint" id="{e(hint_id)}">{e(hint)}</p>' if hint else ""

    return (
        f'<div class="{" ".join(wrap_cls)}">'
        f'<label class="r-field__label" for="{e(fid)}">{e(label)}{req_mark}</label>'
        f"<input{_attrs(inp)}>"
        f"{hint_html}"
        f'<span class="r-field__error" id="{e(err_id)}" role="alert">{e(error)}</span>'
        f"</div>"
    )


def card(
    inner: str,
    *,
    title: str = "",
    text: str = "",
    raised: bool = False,
    flush: bool = False,
    element_id: str = "",
    classes: str = "",
    tag: str = "div",
    attrs: dict | None = None,
) -> str:
    """Карточка. raised — тень вместо границы.

    Либо граница, либо тень, не оба сразу: 1px рамка под широкой мягкой тенью
    даёт «призрачную карточку», у которой не понять, где её край.

    Вложенных карточек не делаем: вторая рамка внутри первой — это список или
    таблица, которые не захотели так назвать.
    """
    cls = ["r-card"]
    if raised:
        cls.append("r-card--raised")
    if flush:
        cls.append("r-card--flush")
    if classes:
        cls.append(classes)

    head = ""
    if title:
        head += f'<h2 class="r-card__title">{e(title)}</h2>'
    if text:
        head += f'<p class="r-card__text">{e(text)}</p>'

    a = dict(attrs or {})
    a["class"] = " ".join(cls)
    a["id"] = element_id
    return f"<{tag}{_attrs(a)}>{head}{inner}</{tag}>"


def status(label: str, tone: StatusTone = "neutral", *, icon: str = "") -> str:
    """Плашка-статус.

    Слово в плашке обязательно: цвет один смысл не несёт — его не видит
    ни дальтоник, ни человек с выключенными цветами в системе.
    """
    icon_html = f'<span aria-hidden="true">{icon}</span>' if icon else ""
    return f'<span class="r-status r-status--{e(tone)}">{icon_html}{e(label)}</span>'


def empty_state(
    title: str,
    *,
    text: str = "",
    action_label: str = "",
    action_href: str = "",
    element_id: str = "",
) -> str:
    """Пустое состояние нового слоя.

    Старое — app/web/components/empty_state.py, оно остаётся работать на
    страницах, которые ещё не переехали. Второго вида на одной странице
    быть не должно: переводите блок целиком.
    """
    text_html = f'<p class="r-empty__text">{e(text)}</p>' if text else ""
    action_html = ""
    if action_label and action_href:
        action_html = (
            '<div class="r-empty__action">'
            + button(action_label, kind="secondary", href=action_href)
            + "</div>"
        )
    attrs = f' id="{e(element_id)}"' if element_id else ""
    return (
        f'<div class="r-empty"{attrs}>'
        f'<p class="r-empty__title">{e(title)}</p>'
        f"{text_html}{action_html}"
        f"</div>"
    )


# =====================================================================
# ВИТРИНА: монограмма, услуга, свободное окно, карточка салона, лист снизу
#
# Эти элементы живут здесь, а не в страницах, по той же причине, что кнопка:
# карточка салона нужна И каталогу, И главной, и «похожая вторая» через месяц
# разойдётся с первой (решение 0011: главная показывает ТОТ ЖЕ компонент).
# Составные элементы собраны из примитивов выше — своих цветов и отступов у
# них нет.
# =====================================================================

def mark(letter: str, *, image: str = "", alt: str = "", size: str = "md") -> str:
    """Монограмма: крупная буква вместо фотографии.

    Фотографий у нас почти нет (на проде обложка у двух салонов из девяти), и
    пустое место там, где ждут снимок, читается как поломка. Буква антиквой —
    это решение: она занимает то же место и ничего не обещает. Градиентных
    заглушек не рисуем — декорация на месте содержания видна сразу.
    """
    cls = f"r-mark r-mark--{size}"
    if image:
        return (
            f'<span class="{cls}">'
            f'<img src="{e(image)}" alt="{e(alt)}" loading="lazy" decoding="async">'
            f"</span>"
        )
    return f'<span class="{cls}" aria-hidden="true">{e((letter or "?")[0].upper())}</span>'


def service_line(name: str, *, price: str, duration: str = "", old_price: str = "") -> str:
    """Строка услуги: название, время, цена. Не карточка.

    Вложенных карточек не делаем, а список услуг внутри карточки салона — это
    именно список: его держат линии между строками, а не вторая рамка.

    ``old_price`` — цена до скидки (вечерние окна). Зачёркивание само по себе
    смысла не несёт для скринридера, поэтому рядом скрытая подпись «было».
    """
    dur = f'<span class="r-svc__dur">{e(duration)}</span>' if duration else ""
    old = (
        f'<s class="r-svc__old"><span class="r-sr">было </span>{e(old_price)}</s>'
        if old_price else ""
    )
    return (
        '<li class="r-svc__row">'
        f'<span class="r-svc__name">{e(name)}</span>'
        f"{dur}"
        f'<span class="r-svc__price">{old}{e(price)}</span>'
        "</li>"
    )


def slot(label: str, *, href: str = "", value: str = "", classes: str = "",
         title: str = "") -> str:
    """Свободное окно. С href — ссылка (из каталога ведёт в запись), без —
    кнопка (внутри страницы салона выбор уже не требует перехода).

    ``title`` — полная дата. Подпись короткая («сегодня 15:00») и считается во
    времени САЛОНА: приходить надо по его часам. Для посетителя из другого
    пояса «сегодня» может означать его завтра, поэтому точная дата всегда
    доступна наведением и длинным нажатием.
    """
    cls = ("r-slot " + classes).strip()
    tip = f' title="{e(title)}"' if title else ""
    if href:
        return f'<a class="{cls}" href="{e(href)}" data-slot="{e(value)}"{tip}>{e(label)}</a>'
    return (
        f'<button type="button" class="{cls}" data-slot="{e(value)}"{tip}>'
        f"{e(label)}</button>"
    )


def salon_card(
    *,
    salon_id: int,
    name: str,
    href: str,
    kind_label: str = "",
    city: str = "",
    rating: float = 0.0,
    reviews: int = 0,
    logo_url: str = "",
    badges: tuple = (),
    services: tuple = (),
    services_total: int = 0,
    slots: tuple = (),
    slot_service: str = "",
    promos: tuple = (),
    favorite_icons: tuple = (),
    favorite_on: bool = False,
    all_label: str = "Все услуги и запись",
) -> str:
    """Карточка салона или мастера для каталога и главной.

    Что её несёт: имя, город, услуги с ценой и временем, ближайшие свободные
    окна. Фотография улучшает, но ничего не держит — её отсутствие не оставляет
    в карточке дыры (решение 0011, п. 11 и 12).

    ``services`` — готовые строки от ``service_line``; ``slots`` — от ``slot``.
    Карточка не знает, откуда взялись цена и окно, и не считает их сама.

    Класс ``salon-card`` рядом с ``r-salon`` — зацепка для скриптов каталога
    (догрузка «показать ещё» считает карточки по нему); оформление висит
    только на ``r-salon``.
    """
    heart, heart_filled = (favorite_icons or ("", ""))
    fav = ""
    if heart:
        # favorite_on рисует сердечко уже закрашенным на сервере. Нужно
        # избранному: там в избранном ВСЁ, и дорисовка скриптом после загрузки
        # давала бы вспышку пустых сердечек на каждой карточке. Подпись тоже
        # меняется — иначе кнопка, которая убирает, называется «В избранное».
        fav = (
            f'<button class="favorite-btn r-salon__fav{" liked" if favorite_on else ""}" '
            f'type="button" data-type="salon" '
            f'data-id="{salon_id}" data-icon-heart="{heart.replace(chr(34), "&quot;")}" '
            f'data-icon-heart-filled="{heart_filled.replace(chr(34), "&quot;")}" '
            f'aria-pressed="{"true" if favorite_on else "false"}" '
            f'aria-label="{"Убрать из избранного" if favorite_on else "В избранное"}" '
            f'title="{"Убрать из избранного" if favorite_on else "В избранное"}">'
            f'<span class="heart-icon">{heart_filled if favorite_on else heart}</span>'
            f"</button>"
        )

    # Оценку показываем только когда она есть. «0.0» — это не «плохо», а «нет
    # данных»: на части салонов reviews_count заполнен, а rating нулевой, и
    # бейдж «0.0 (312)» читался как единица с тремя сотнями подтверждений.
    #
    # Она стоит в той же строке, что тип и город, а не отдельным столбцом
    # справа: в сетке на 1024px колонка карточки около 350px, и оценка сбоку
    # отбирала у имени столько, что «Радуга» переносилась по слогам.
    rating_html = ""
    if rating and rating > 0:
        rating_html = (
            '<span class="r-salon__rating" title="Оценка по отзывам">'
            f'<span class="r-salon__star" aria-hidden="true">{ICON_STAR_FILLED}</span>'
            f'{rating:.1f}'
            + (f'<span class="r-salon__reviews">({reviews})</span>' if reviews else "")
            + "</span>"
        )

    where = " · ".join(p for p in (kind_label, city) if p)
    where_html = ""
    if where or rating_html:
        where_html = (
            '<span class="r-salon__where">'
            + (f"{e(where)} " if where else "")
            + rating_html + "</span>"
        )
    tags_html = f'<div class="r-salon__tags">{"".join(badges)}</div>' if badges else ""

    # Акция — СТРОКА, а не пилюля. Метка салона коротка по смыслу («Победитель
    # конкурса Руми»), а акция — это предложение целиком: «Новым клиентам»
    # плюс «Скидка первым посетителям 20%». В пилюле такой текст не переносится
    # и вылезает за край карточки, а радиус 999 по договорённости вообще только
    # для небольших управляющих элементов (docs/design.md).
    promos_html = ""
    if promos:
        items = "".join(
            f'<li><span class="r-salon__promo-tag">{e(tag)}</span>{e(title)}</li>'
            if tag else f"<li>{e(title)}</li>"
            for tag, title in promos[:2]
        )
        promos_html = f'<ul class="r-salon__promos">{items}</ul>'

    svc_html = ""
    if services:
        more = ""
        extra = services_total - len(services)
        if extra > 0:
            more = f'<li class="r-svc__more">и ещё {extra}</li>'
        svc_html = f'<ul class="r-svc">{"".join(services)}{more}</ul>'
    else:
        # Пустое место там, где у соседних карточек цены, читается как сбой
        # загрузки. Одна строка превращает его в факт.
        svc_html = '<p class="r-svc__none">Услуги пока не выложены</p>'

    slots_html = ""
    if slots:
        label = "Ближайшее время"
        if slot_service:
            label += f" · {slot_service}"
        slots_html = (
            '<div class="r-salon__slots">'
            f'<p class="r-salon__slots-label">{e(label)}</p>'
            f'<div class="r-slots">{"".join(slots)}</div>'
            "</div>"
        )

    return (
        f'<article class="r-salon salon-card" data-salon-id="{salon_id}">'
        f'<div class="r-salon__top">'
        f'<a class="r-salon__face" href="{e(href)}" data-salon-link="{salon_id}">'
        f"{mark(name, image=logo_url, alt=name, size='lg')}"
        f'<span class="r-salon__id">'
        f'<span class="r-salon__name">{e(name)}</span>'
        + where_html
        + "</span></a>"
        f'<div class="r-salon__aside">{fav}</div>'
        "</div>"
        f"{tags_html}{promos_html}{svc_html}{slots_html}"
        f'<a class="r-salon__all" href="{e(href)}">{e(all_label)}</a>'
        "</article>"
    )


def sheet(inner: str, *, element_id: str, title: str, close_label: str = "Закрыть") -> str:
    """Лист снизу: на телефоне диалог приезжает оттуда, где палец.

    Движение листа живёт в static/src/js/motion.js (пресет sheet: демпфирование
    0.8, отклик 0.3) и прерывается на середине. Разметка здесь — настоящий
    диалог: role, aria-modal и подпись, иначе скринридер читает страницу под
    листом как доступную.

    Затемнение — отдельный элемент, а не ::before у панели: по нему нужно
    кликать, а у панели должен оставаться свой обработчик прокрутки.
    """
    tid = f"{element_id}-title"
    return f"""
<div class="r-sheet" id="{e(element_id)}" hidden>
    <div class="r-sheet__scrim" data-sheet-close></div>
    <div class="r-sheet__panel" role="dialog" aria-modal="true" aria-labelledby="{e(tid)}">
        <div class="r-sheet__head">
            <span class="r-sheet__grip" aria-hidden="true"></span>
            <h2 class="r-sheet__title" id="{e(tid)}">{e(title)}</h2>
            <button class="r-sheet__close" type="button" data-sheet-close
                    aria-label="{e(close_label)}">
                <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
                     stroke-width="2" stroke-linecap="round" aria-hidden="true">
                    <path d="M18 6 6 18M6 6l12 12"/>
                </svg>
            </button>
        </div>
        <div class="r-sheet__body">{inner}</div>
    </div>
</div>"""


def dock(inner: str, *, element_id: str = "") -> str:
    """Закреплённая снизу полоса с главным действием (телефон).

    safe-area обязателен: на айфоне без него кнопка попадает под полосу жеста
    «домой», и запись оказывается в сантиметре от промаха.
    """
    attrs = f' id="{e(element_id)}"' if element_id else ""
    return f'<div class="r-dock"{attrs}>{inner}</div>'


def section_head(title: str, *, text: str = "", link_label: str = "", link_href: str = "",
                 display: bool = False) -> str:
    """Заголовок раздела страницы: название, подзаголовок и ссылка «все».

    Кикеров и надзаголовков над заголовком нет — заголовок несёт себя сам.
    """
    cls = "r-display" if display else "r-title"
    link = ""
    if link_label and link_href:
        link = f'<a class="r-seclink" href="{e(link_href)}">{e(link_label)}</a>'
    sub = f'<p class="r-sechead__text r-text r-muted">{e(text)}</p>' if text else ""
    return (
        '<div class="r-sechead">'
        f'<div class="r-sechead__main"><h2 class="{cls}">{e(title)}</h2>{sub}</div>'
        f"{link}</div>"
    )


def deal_card(
    *,
    salon_id: int,
    name: str,
    href: str,
    address: str = "",
    discount_label: str = "",
    masters: tuple = (),
    action_label: str = "Записаться со скидкой",
    action_icon: str = "",
) -> str:
    """Карточка предложения «вечерние окна со скидкой».

    Собрана из тех же частей, что карточка каталога (``.r-salon``, монограмма,
    строки услуг, окна), — переход из каталога сюда не должен выглядеть
    переходом на другой сайт. Отличается тем, что внутри несколько мастеров:
    предложение идёт от конкретного человека, а не от «салона вообще».

    ``masters`` — кортежи ``(имя, специализация, окна, услуги)``, где окна —
    готовые строки от ``slot``, услуги — от ``service_line``. Мастера разделены
    линией, а не вложенными рамками.

    Скидка — слово в плашке («Скидка −20%»), а не один зелёный цвет.
    """
    where = f'<span class="r-salon__where">{e(address)}</span>' if address else ""
    badge = status(discount_label, "success") if discount_label else ""
    blocks = ""
    for m_name, m_spec, m_slots, m_services in masters:
        spec = f'<span class="r-deal__spec">{e(m_spec)}</span>' if m_spec else ""
        blocks += (
            '<section class="r-deal__master">'
            f'<h3 class="r-deal__who"><span class="r-deal__name">{e(m_name)}</span>{spec}</h3>'
            '<p class="r-salon__slots-label">Свободно вечером</p>'
            f'<div class="r-slots">{"".join(m_slots)}</div>'
            f'<ul class="r-svc">{"".join(m_services)}</ul>'
            "</section>"
        )
    return (
        f'<article class="r-salon r-deal" data-salon-id="{salon_id}">'
        '<div class="r-salon__top">'
        f'<a class="r-salon__face" href="{e(href)}">'
        f"{mark(name, size='lg')}"
        f'<span class="r-salon__id"><span class="r-salon__name">{e(name)}</span>{where}</span>'
        "</a>"
        f'<div class="r-salon__aside">{badge}</div>'
        "</div>"
        f"{blocks}"
        f'<div class="r-deal__action">'
        + button(action_label, href=href, block=True, icon=action_icon)
        + "</div></article>"
    )


# =====================================================================
# КАБИНЕТ: факты, раскрывающийся блок, карточка человека, уведомление
#
# Эти элементы заведены заходом «кабинет клиента». Кабинет — продолжение
# витрины, поэтому он не рисует своих кнопок и карточек, а берёт их отсюда;
# всё, чего ему не хватило, доехало в этот файл, а не в его страницы.
# =====================================================================

def facts(items: tuple, *, inline: bool = False) -> str:
    """Список «подпись — значение». Настоящий <dl>, а не две колонки <div>.

    Зачем: и в записи («когда», «где», «сколько»), и в профиле («телефон»,
    «город») одно и то же — пара, у которой есть смысловая связь. Скринридер
    читает <dl> парами, а набор <span> — сплошным текстом, в котором не
    понять, где кончилась подпись и началось значение.

    ``items`` — последовательность пар ``(подпись, значение)``; значение уже
    готовая разметка (там бывает ссылка), поэтому его НЕ экранируем — вызов
    обязан прогнать текст через e() сам. Пустое значение пропускается: пустая
    строка в списке фактов читается как потерянные данные.

    ``inline`` — для коротких пар в одну строку (где/когда у записи).
    """
    rows = "".join(
        f"<div class=\"r-facts__row\"><dt>{e(label)}</dt><dd>{value}</dd></div>"
        for label, value in items
        if value not in (None, "")
    )
    if not rows:
        return ""
    cls = "r-facts r-facts--inline" if inline else "r-facts"
    return f'<dl class="{cls}">{rows}</dl>'


def disclosure(summary: str, inner: str, *, element_id: str = "", icon: str = "",
               open_: bool = False) -> str:
    """Раскрывающийся блок на <details>, а не на кнопке с обработчиком.

    Прежний аккордеон профиля был <button> плюс класс is-active из JS: без
    скрипта (или до его загрузки) формы смены телефона и пароля не
    открывались вовсе, а скринридер не знал, раскрыт блок или нет.
    <details> умеет это сам, поиском по странице раскрывается браузером и
    печатается раскрытым.

    Стрелку рисует CSS через ::after у summary — своей разметки для неё нет:
    маркер <summary> в разных браузерах разный, его снимаем в CSS.
    """
    attrs = {"class": "r-disc", "id": element_id}
    if open_:
        attrs["open"] = True
    icon_html = f'<span class="r-disc__icon" aria-hidden="true">{icon}</span>' if icon else ""
    return (
        f"<details{_attrs(attrs)}>"
        f'<summary class="r-disc__head">{icon_html}'
        f'<span class="r-disc__label">{e(summary)}</span></summary>'
        f'<div class="r-disc__body">{inner}</div>'
        f"</details>"
    )


def person_card(
    *,
    name: str,
    href: str,
    meta: str = "",
    where: str = "",
    rating: float = 0.0,
    avatar_url: str = "",
    aside: str = "",
    footer: str = "",
    all_label: str = "",
) -> str:
    """Карточка человека: мастер в избранном.

    Устроена как ``salon_card`` — монограмма, имя, строка «кто и где», ссылка
    внизу, — чтобы избранное не выглядело вторым набором карточек. Отдельная
    функция, а не флаг у salon_card: у мастера нет ни услуг с ценами, ни окон,
    и карточка с пятью пустыми ветками читается хуже двух честных.
    """
    rating_html = ""
    if rating and rating > 0:
        rating_html = (
            '<span class="r-salon__rating" title="Оценка по отзывам">'
            f'<span class="r-salon__star" aria-hidden="true">{ICON_STAR_FILLED}</span>'
            f"{rating:.1f}</span>"
        )
    line = " · ".join(p for p in (meta, where) if p)
    where_html = ""
    if line or rating_html:
        where_html = (
            '<span class="r-salon__where">'
            + (f"{e(line)} " if line else "")
            + rating_html + "</span>"
        )
    foot = ""
    if all_label:
        foot = f'<a class="r-salon__all" href="{e(href)}">{e(all_label)}</a>'
    return (
        '<article class="r-salon r-salon--person">'
        '<div class="r-salon__top">'
        f'<a class="r-salon__face" href="{e(href)}">'
        f"{mark(name, image=avatar_url, alt=name, size='lg')}"
        f'<span class="r-salon__id"><span class="r-salon__name">{e(name)}</span>'
        + where_html
        + "</span></a>"
        f'<div class="r-salon__aside">{aside}</div>'
        "</div>"
        f"{footer}{foot}"
        "</article>"
    )


def notice(text: str, *, tone: StatusTone = "neutral", element_id: str = "") -> str:
    """Короткое сообщение о результате действия («Пароль изменён»).

    role=status, а не просто цветная плашка: страница перезагружается после
    POST, и человек, который не видит экран, иначе никак не узнает, что
    сохранение прошло.

    Ошибка идёт с role=alert — её читают сразу, не дожидаясь паузы.
    """
    role = "alert" if tone == "danger" else "status"
    attrs = {"class": f"r-notice r-notice--{tone}", "id": element_id, "role": role}
    return f"<p{_attrs(attrs)}>{e(text)}</p>"
