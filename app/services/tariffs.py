# app/services/tariffs.py
"""Каталог платных тарифов бизнеса — единственный источник правды для СУММ,
которые уходят в Т-Кассу. Витринные тексты/фичи тарифов (для UI) живут
отдельно в app/web/pages/business_checkout.py — здесь только то, что нужно
для расчёта и проверки суммы платежа на сервере (клиенту в этом вопросе не
доверяем: сумма всегда пересчитывается здесь, а не берётся из запроса).

«Индивидуальный» (custom) тариф сюда сознательно не входит — цена «по
запросу», самостоятельная оплата для него не предусмотрена (см. checkout).
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


class TariffError(ValueError):
    """Неверный план или количество сотрудников — платёж не создаём."""


@dataclass(frozen=True)
class Tariff:
    plan: str
    name: str
    # per_employee: amount = unit_price * employee_count; progressive: сумма
    # для lite задаётся ступенчато; flat: фиксированная сумма в месяц.
    billing: str  # "per_employee" | "progressive" | "flat"
    unit_price: Optional[Decimal] = None
    amount: Optional[Decimal] = None
    min_employees: Optional[int] = None
    max_employees: Optional[int] = None
    second_employee_amount: Optional[Decimal] = None
    additional_employee_price: Optional[Decimal] = None


TARIFF_CATALOG: dict[str, Tariff] = {
    "lite": Tariff(
        plan="lite", name="Лайт", billing="progressive",
        unit_price=Decimal("399"), second_employee_amount=Decimal("599"),
        additional_employee_price=Decimal("240"), min_employees=1, max_employees=5,
    ),
    "business": Tariff(
        plan="business", name="Бизнес", billing="flat", amount=Decimal("3500"),
    ),
    "corporate": Tariff(
        plan="corporate", name="Корпоративный", billing="flat", amount=Decimal("6990"),
    ),
}

# Исторические тарифы моделей. Новое подключение и автопродление отключены;
# каталог оставлен для обработки платежей, созданных до перехода на бесплатный
# моделинг.
MODEL_TARIFF_CATALOG: dict[str, Tariff] = {
    "start": Tariff(plan="start", name="Старт", billing="flat", amount=Decimal("490")),
    "pro": Tariff(plan="pro", name="Про", billing="flat", amount=Decimal("990")),
    "premium": Tariff(plan="premium", name="Премиум", billing="flat", amount=Decimal("1990")),
}


def compute_amount(
    plan: str, employee_count: Optional[int] = None,
    catalog: dict[str, Tariff] = TARIFF_CATALOG,
) -> Decimal:
    """Сумма месячного платежа по тарифу. Кидает TariffError на невалидный
    план (в т.ч. 'custom' — для него нет самостоятельной оплаты) или
    некорректное количество сотрудников для тарифа «Лайт»."""
    tariff = catalog.get(plan)
    if tariff is None:
        raise TariffError(f"Тариф «{plan}» недоступен для самостоятельной оплаты")

    if tariff.billing == "flat":
        return tariff.amount

    if employee_count is None:
        raise TariffError("Для тарифа «Лайт» нужно указать количество сотрудников")
    if not (tariff.min_employees <= employee_count <= tariff.max_employees):
        raise TariffError(
            f"Тариф «{tariff.name}» — от {tariff.min_employees} до "
            f"{tariff.max_employees} сотрудников (указано {employee_count})"
        )
    if tariff.billing == "progressive":
        if employee_count == 1:
            return tariff.unit_price
        return tariff.second_employee_amount + tariff.additional_employee_price * (employee_count - 2)
    return tariff.unit_price * employee_count


def resolve_plan_for_employee_count(employee_count: int) -> str:
    """Тариф бизнеса по фактическому числу мастеров — салон стартует с
    выбранного вручную тарифа (см. checkout/billing-tab), но при каждой
    следующей оплате (ручной или автосписании, см. app/tasks.py:
    charge_due_subscriptions) план пересчитывается заново по этой функции:
    подрос штат — на следующий платёж тариф сам подтянется вверх, и наоборот.
    Возвращает 'custom', если сотрудников больше, чем покрывает
    «Корпоративный» (>20) — для него самостоятельной оплаты нет, дальше
    решает продавец (см. TariffError в compute_amount)."""
    count = max(employee_count, 1)
    if count <= TARIFF_CATALOG["lite"].max_employees:
        return "lite"
    if count <= 10:
        return "business"
    if count <= 20:
        return "corporate"
    return "custom"
