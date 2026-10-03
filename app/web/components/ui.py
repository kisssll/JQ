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
    element_id: str = "",
    block: bool = False,
    small: bool = False,
    disabled: bool = False,
    loading: bool = False,
    icon: str = "",
    classes: str = "",
    data: dict | None = None,
    aria_label: str = "",
) -> str:
    """Кнопка. С href — ссылка, выглядящая и ведущая себя как кнопка.

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
        if disabled:
            link["aria-disabled"] = "true"
            link["tabindex"] = "-1"
        return f"<a{_attrs(link)}>{inner}</a>"

    btn = dict(common)
    btn["type"] = type_
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
