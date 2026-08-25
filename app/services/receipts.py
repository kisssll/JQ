"""Кассовый чек (54-ФЗ) для платежей Т-Кассы.

Чек мы не рисуем сами: передаём в Init блок Receipt, касса пробивает чек
через ОФД и сама доставляет его плательщику на email/телефон. Наше дело —
корректно описать позиции и указать, куда доставить.

Главное инвариантное правило: сумма позиций обязана в точности совпадать с
суммой платежа. Касса отвергает Init при расхождении хотя бы на копейку,
поэтому весь счёт ведётся в копейках, а не в рублях с плавающей точкой.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from app.core.config import settings
from app.services.tkassa import rubles_to_kopecks

logger = logging.getLogger(__name__)

# Наименование позиции ограничено 128 символами (требование ФФД).
_NAME_LIMIT = 128


def _item(name: str, price_kop: int, quantity: int = 1) -> dict:
    return {
        "Name": name[:_NAME_LIMIT],
        "Price": price_kop,
        "Quantity": quantity,
        "Amount": price_kop * quantity,
        "Tax": settings.RECEIPT_TAX,
        "PaymentMethod": "full_payment",
        "PaymentObject": "service",
    }


def _contacts(email: Optional[str], phone: Optional[str]) -> dict:
    """Куда касса доставит чек. Хотя бы одно поле обязано быть заполнено —
    иначе чек некуда отправить и Init упадёт. Телефон есть у всех
    (модель телефон-центрична), почта — далеко не всегда."""
    out: dict = {}
    if email:
        out["Email"] = email.strip()
    if phone:
        out["Phone"] = phone.strip()
    return out


def subscription_receipt(
    *, total_rub: Decimal, monthly_rub: Optional[Decimal], months: int,
    plan_title: str, email: Optional[str], phone: Optional[str],
) -> Optional[dict]:
    """Чек за подписку: «тариф × месяцы» плюс, если сумма больше, отдельная
    строка доплаты за рост штата (см. subscription.register_headcount) —
    иначе человек видит незнакомую сумму без объяснения.

    None означает «чек собрать не из чего» (нет ни почты, ни телефона) —
    вызывающий решает, что с этим делать.
    """
    contacts = _contacts(email, phone)
    if not contacts:
        return None

    total_kop = rubles_to_kopecks(total_rub)
    items: list[dict] = []

    monthly_kop = rubles_to_kopecks(monthly_rub) if monthly_rub is not None else 0
    months = max(1, int(months or 1))
    base_kop = monthly_kop * months

    if 0 < base_kop <= total_kop:
        items.append(_item(f"Доступ к сервису Руми, тариф «{plan_title}»",
                           monthly_kop, months))
        extra_kop = total_kop - base_kop
        if extra_kop > 0:
            items.append(_item("Доплата за увеличение числа мастеров", extra_kop))
    else:
        # Разложить не удалось (нет месячной цены либо она больше итога —
        # например, ручная правка суммы). Одна честная строка на весь платёж
        # лучше, чем чек, который касса отвергнет.
        items.append(_item(f"Доступ к сервису Руми, тариф «{plan_title}»", total_kop))

    receipt = {**contacts, "Taxation": settings.RECEIPT_TAXATION, "Items": items}
    _assert_balanced(receipt, total_kop)
    return receipt


def verification_receipt(
    *, amount_rub: Decimal, email: Optional[str], phone: Optional[str],
) -> Optional[dict]:
    """Чек за верификационный рубль при привязке карты. Деньги реально
    списываются и тут же возвращаются, поэтому расчёт есть и чек нужен —
    касса пробьёт приход, а на возврат сформирует чек возврата."""
    contacts = _contacts(email, phone)
    if not contacts:
        return None
    kop = rubles_to_kopecks(amount_rub)
    receipt = {
        **contacts,
        "Taxation": settings.RECEIPT_TAXATION,
        "Items": [_item("Проверка карты для автоплатежа", kop)],
    }
    _assert_balanced(receipt, kop)
    return receipt


def _assert_balanced(receipt: dict, total_kop: int) -> None:
    """Расхождение суммы позиций с суммой платежа — отказ Init, то есть
    несостоявшаяся оплата. Ловим у себя и громко, а не по коду ошибки кассы."""
    items_sum = sum(i["Amount"] for i in receipt["Items"])
    if items_sum != total_kop:
        raise ValueError(
            f"чек не сходится: позиции {items_sum} коп, платёж {total_kop} коп"
        )
