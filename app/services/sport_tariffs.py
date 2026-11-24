# app/services/sport_tariffs.py
"""Тарифы платформы Руми Спорт и расчёт стоимости для клубов и тренеров.

Правила:
- Для отдельных (персональных/частных) тренеров: 399 ₽/мес (как одиночный мастер в бьюти).
- Для одного спортзала / клуба: 3 500 ₽/мес.
- Для сетей из 2 и более залов: 3 500 ₽ + 2 500 ₽ за каждый последующий зал.
  (1 зал = 3 500 ₽; 2 зала = 6 000 ₽; 3 зала = 8 500 ₽; N залов = 3 500 + (N-1)*2 500).
- Индивидуальные предложения (custom offer): фиксированная сумма, закреплённая
  администратором через панель модерации (переопределяет стандартный алгоритм).
"""
from typing import Optional

SPORT_COACH_MONTHLY_PRICE: int = 399
SPORT_GYM_BASE_MONTHLY_PRICE: int = 3500
SPORT_ADDITIONAL_VENUE_PRICE: int = 2500
SPORT_MAX_STANDARD_VENUES: int = 15


def calculate_sport_monthly_price(
    venues_count: int = 1,
    is_coach: bool = False,
    custom_price: Optional[int] = None,
) -> int:
    """Расчёт месячной стоимости сервиса для спорта.

    Если задан custom_price, закреплённый за организацией администратором,
    возвращается именно он.
    """
    if custom_price is not None:
        return max(0, int(custom_price))

    if is_coach:
        return SPORT_COACH_MONTHLY_PRICE

    count = max(1, int(venues_count or 1))
    if count == 1:
        return SPORT_GYM_BASE_MONTHLY_PRICE
    return SPORT_GYM_BASE_MONTHLY_PRICE + (count - 1) * SPORT_ADDITIONAL_VENUE_PRICE


def get_sport_calculator_pricing_table(max_venues: int = SPORT_MAX_STANDARD_VENUES) -> dict[str, dict]:
    """Справочная таблица цен для гидратации клиентского калькулятора."""
    pricing: dict[str, dict] = {
        "coach": {
            "amount": SPORT_COACH_MONTHLY_PRICE,
            "title": "Тариф «Тренер»",
            "description": "Для персональных тренеров и независимых инструкторов.",
        }
    }
    for count in range(1, max_venues + 1):
        amount = calculate_sport_monthly_price(venues_count=count, is_coach=False)
        if count == 1:
            desc = "1 зал со всей командой тренеров и расписанием."
            plan = "gym"
        else:
            desc = f"Сеть из {count} залов: 3 500 ₽ за основной зал + {count - 1} × 2 500 ₽."
            plan = "chain"
        pricing[str(count)] = {
            "amount": amount,
            "plan": plan,
            "description": desc,
        }
    return pricing
