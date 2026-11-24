import pytest
from app.services.sport_tariffs import (
    SPORT_ADDITIONAL_VENUE_PRICE,
    SPORT_COACH_MONTHLY_PRICE,
    SPORT_GYM_BASE_MONTHLY_PRICE,
)


async def test_sport_tariffs_page_renders_calculator_and_plans(client):
    response = await client.get("/sport/tariffs")
    assert response.status_code == 200
    html = response.text

    # Title & eyebrow
    assert "Тарифы и информация" in html
    assert "Руми Спорт · тарифы" in html

    # Calculator elements
    assert "data-sport-calculator" in html
    assert "Я отдельный тренер" in html
    assert "Спортзал / сеть" in html
    assert "Сколько залов или филиалов у вас?" in html
    assert f"{SPORT_COACH_MONTHLY_PRICE} ₽" in html
    assert "3 500 ₽" in html
    assert "2 500 ₽" in html

    # Tariff plans cards
    assert "Тренер" in html
    assert "Спортивный клуб" in html
    assert "Спортивная сеть" in html
    assert "Индивидуальный" in html

    # Tabs
    assert "Тарифы и калькулятор" in html
    assert "Документы" in html
    assert "Инструкции" in html

    # Documents tab
    docs_resp = await client.get("/sport/tariffs?tab=documents")
    assert docs_resp.status_code == 200
    assert "Условия использования платформы для спортивных клубов" in docs_resp.text
    assert "Согласие на обработку персональных данных" in docs_resp.text

    # Guides tab
    guides_resp = await client.get("/sport/tariffs?tab=guides")
    assert guides_resp.status_code == 200
    assert "Как подключить спортивный клуб к платформе" in guides_resp.text
    assert "Как работает индивидуальная запись к тренерам" in guides_resp.text
