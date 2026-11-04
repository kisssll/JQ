# app/web/tariff_presentation.py
"""Витринное описание тарифов: подпись по размеру салона и состав.

Зачем отдельный модуль. Тексты жили внутри business_checkout.py, поэтому
вкладка «Тариф» в панели показывала только название и цену — чтобы понять,
чем «Лайт» отличается от «Бизнеса», владельцу приходилось уходить на лендинг.

Цены здесь сознательно НЕ дублируются. Суммы берутся из
app.services.tariffs.TARIFF_CATALOG — он единственный источник правды для
Т-Кассы, и витрина не должна уметь с ним разойтись. Раньше цена лежала и
там, и тут («3 500 ₽» строкой против Decimal("3500")).

«Индивидуальный» (custom) в TARIFF_CATALOG отсутствует намеренно: цена по
запросу, самостоятельной оплаты нет — поэтому у него здесь свой price_label.
"""
from app.services.tariffs import TARIFF_CATALOG

CUSTOM_PLAN = "custom"

# Порядок = порядок показа карточек, от младшего к старшему.
PLAN_ORDER = ("lite", "business", "corporate", CUSTOM_PLAN)

PLAN_COPY: dict[str, dict] = {
    "lite": {
        "name": "Лайт",
        "size": "1–5 мастеров · цена зависит от размера команды",
        # Цены ступеней подставляются из каталога (_lite_steps): вписанные
        # строкой, они разошлись бы с Т-Кассой на первой же смене прайса —
        # ровно от этого модуль и заводился, см. шапку файла.
        "features": [
            "{lite_first}",
            "{lite_rest}",
            "Управление расписанием",
            "Онлайн-запись клиентов",
            "Базовая аналитика",
        ],
    },
    "business": {
        "name": "Бизнес",
        "size": "6–10 сотрудников",
        "features": [
            "Расширенная аналитика",
            "Приоритет в выдаче",
            "Акции и программы лояльности",
            "Персональная поддержка",
        ],
    },
    "corporate": {
        "name": "Корпоративный",
        "size": "11–20 сотрудников",
        "features": [
            "Мульти-филиалы",
            "VIP поддержка",
            "Индивидуальные интеграции",
            "Расширенная отчётность",
            "Выделенный менеджер",
        ],
    },
    CUSTOM_PLAN: {
        "name": "Индивидуальный",
        "size": "Более 20 сотрудников",
        "features": [
            "Всё из тарифа «Корпоративный»",
            "Индивидуальные условия",
            "Персональный SLA",
        ],
    },
}


def _lite_steps() -> dict[str, str]:
    """Подписи ступеней «Лайта» — из каталога, не руками.

    Прайс ступенчатый: первый мастер по unit_price, второй — по
    second_employee_amount, каждый следующий добавляет
    additional_employee_price. Потолок считаем по max_employees, чтобы
    «до N ₽» не пришлось править вслед за ценами.
    """
    t = TARIFF_CATALOG["lite"]
    top = t.second_employee_amount + t.additional_employee_price * (t.max_employees - 2)
    return {
        "lite_first": (f"1 мастер — {_money(t.unit_price)} ₽/мес; "
                       f"2 мастера — {_money(t.second_employee_amount)} ₽/мес"),
        "lite_rest": (f"3–{t.max_employees} мастеров — +{_money(t.additional_employee_price)} ₽ "
                      f"за каждого начиная с 3-го (до {_money(top)} ₽/мес)"),
    }


def _money(value) -> str:
    return f"{int(value):,}".replace(",", " ")


def price_parts(plan: str) -> tuple[str, str]:
    """(сумма, период) для карточки. Считается из TARIFF_CATALOG."""
    if plan == CUSTOM_PLAN:
        return "По запросу", ""
    tariff = TARIFF_CATALOG.get(plan)
    if not tariff:
        return "—", ""
    if tariff.billing == "progressive":
        return f"От {_money(tariff.unit_price)} ₽", "/мес, зависит от числа мастеров"
    if tariff.billing == "per_employee":
        return f"{_money(tariff.unit_price)} ₽", "за сотрудника/мес"
    return f"{_money(tariff.amount)} ₽", "/мес"


def plan_view(plan: str) -> dict:
    """Всё, что нужно карточке тарифа: имя, размер салона, цена, состав."""
    copy = PLAN_COPY.get(plan, {})
    amount, period = price_parts(plan)
    # Подписи ступеней «Лайта» — из каталога: в PLAN_COPY они стоят метками
    # {lite_first}/{lite_rest}, иначе цена жила бы в двух местах сразу.
    steps = _lite_steps()
    features = [f.format(**steps) if "{" in f else f for f in copy.get("features", [])]
    return {
        "plan": plan,
        "name": copy.get("name", plan),
        "size": copy.get("size", ""),
        "price": amount,
        "period": period,
        "features": features,
    }


def all_plans() -> list[dict]:
    return [plan_view(p) for p in PLAN_ORDER]
