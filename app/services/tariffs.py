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
    # per_employee: amount = unit_price * employee_count (лимит сотрудников
    # тарифа задаёт диапазон). flat: фиксированная сумма в месяц.
    billing: str  # "per_employee" | "flat"
    unit_price: Optional[Decimal] = None
    amount: Optional[Decimal] = None
    min_employees: Optional[int] = None
    max_employees: Optional[int] = None


TARIFF_CATALOG: dict[str, Tariff] = {
    "lite": Tariff(
        plan="lite", name="Лайт", billing="per_employee",
        unit_price=Decimal("250"), min_employees=1, max_employees=5,
    ),
    "business": Tariff(
        plan="business", name="Бизнес", billing="flat", amount=Decimal("3500"),
    ),
    "corporate": Tariff(
        plan="corporate", name="Корпоративный", billing="flat", amount=Decimal("6990"),
    ),
}


def compute_amount(plan: str, employee_count: Optional[int]) -> Decimal:
    """Сумма месячного платежа по тарифу. Кидает TariffError на невалидный
    план (в т.ч. 'custom' — для него нет самостоятельной оплаты) или
    некорректное количество сотрудников для тарифа «Лайт»."""
    tariff = TARIFF_CATALOG.get(plan)
    if tariff is None:
        raise TariffError(f"Тариф «{plan}» недоступен для самостоятельной оплаты")

    if tariff.billing == "flat":
        return tariff.amount

    # per_employee
    if employee_count is None:
        raise TariffError("Для тарифа «Лайт» нужно указать количество сотрудников")
    if not (tariff.min_employees <= employee_count <= tariff.max_employees):
        raise TariffError(
            f"Тариф «{tariff.name}» — от {tariff.min_employees} до "
            f"{tariff.max_employees} сотрудников (указано {employee_count})"
        )
    return tariff.unit_price * employee_count
