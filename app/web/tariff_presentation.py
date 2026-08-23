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
from app.services.tariffs import MODEL_TARIFF_CATALOG, TARIFF_CATALOG

CUSTOM_PLAN = "custom"

# Порядок = порядок показа карточек, от младшего к старшему.
PLAN_ORDER = ("lite", "business", "corporate", CUSTOM_PLAN)

PLAN_COPY: dict[str, dict] = {
    "lite": {
        "name": "Лайт",
        "size": "До 5 сотрудников",
        "features": [
            "Оплата только за сотрудников",
            "Управление расписанием",
            "Онлайн-запись клиентов",
            "Базовая аналитика",
        ],
    },
    "business": {
        "name": "Бизнес",
        "size": "5–10 сотрудников",
        "features": [
            "Расширенная аналитика",
            "Приоритет в выдаче",
            "Акции и программы лояльности",
            "Персональная поддержка",
        ],
    },
    "corporate": {
        "name": "Корпоративный",
        "size": "10–20 сотрудников",
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


def _money(value) -> str:
    return f"{int(value):,}".replace(",", " ")


def price_parts(plan: str) -> tuple[str, str]:
    """(сумма, период) для карточки. Считается из TARIFF_CATALOG."""
    if plan == CUSTOM_PLAN:
        return "По запросу", ""
    tariff = TARIFF_CATALOG.get(plan)
    if not tariff:
        return "—", ""
    if tariff.billing == "per_employee":
        return f"{_money(tariff.unit_price)} ₽", "за сотрудника/мес"
    return f"{_money(tariff.amount)} ₽", "/мес"


def plan_view(plan: str) -> dict:
    """Всё, что нужно карточке тарифа: имя, размер салона, цена, состав."""
    copy = PLAN_COPY.get(plan, {})
    amount, period = price_parts(plan)
    return {
        "plan": plan,
        "name": copy.get("name", plan),
        "size": copy.get("size", ""),
        "price": amount,
        "period": period,
        "features": copy.get("features", []),
    }


def all_plans() -> list[dict]:
    return [plan_view(p) for p in PLAN_ORDER]


# ── Тарифы моделей ───────────────────────────────────────────────────────────
# Та же логика: тексты здесь, суммы — из MODEL_TARIFF_CATALOG. До этого цены
# лежали строками ещё и в app/web/pages/tariffs.py, то есть в третьем месте.

MODEL_PLAN_ORDER = ("start", "pro", "premium")
MODEL_POPULAR = "pro"

MODEL_PLAN_COPY: dict[str, dict] = {
    "start": {
        "name": "Старт",
        "size": "Для тех, кто хочет попробовать",
        "features": [
            "До 3 записей в месяц",
            "Скидка 30% на услуги мастеров",
            "Доступ к начинающим мастерам",
            "Базовое портфолио",
        ],
    },
    "pro": {
        "name": "Про",
        "size": "Самый популярный выбор",
        "features": [
            "До 8 записей в месяц",
            "Скидка 50% на все услуги",
            "Приоритетная запись",
            "Доступ к топ-мастерам",
            "Расширенное портфолио",
            "Эксклюзивные процедуры",
        ],
    },
    "premium": {
        "name": "Премиум",
        "size": "Максимум возможностей",
        "features": [
            "Безлимитные записи",
            "Скидка до 70% на услуги",
            "VIP приоритет на запись",
            "Доступ ко всем мастерам",
            "Персональный менеджер",
            "Фотосессии для портфолио",
            "Ранний доступ к новым салонам",
        ],
    },
}


def model_plan_view(plan: str) -> dict:
    copy = MODEL_PLAN_COPY.get(plan, {})
    tariff = MODEL_TARIFF_CATALOG.get(plan)
    return {
        "plan": plan,
        "name": copy.get("name", plan),
        "size": copy.get("size", ""),
        "price": f"{_money(tariff.amount)} ₽" if tariff else "—",
        "period": "/мес",
        "features": copy.get("features", []),
        "popular": plan == MODEL_POPULAR,
    }


def all_model_plans() -> list[dict]:
    return [model_plan_view(p) for p in MODEL_PLAN_ORDER]
