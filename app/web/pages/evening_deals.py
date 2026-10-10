# app/web/pages/evening_deals.py
"""Публичная страница-подборка «Вечерние окна со скидкой».

Салоны и мастера, у которых сегодня есть свободные вечерние слоты со скидкой.
Скидка применяется автоматически при записи на такой слот (см.
evening_deals_service.evening_deal_discount + create_booking)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.evening_deals_service import build_feed
from app.web.components import ui
from app.web.components.escaping import e
from app.web.components.footer import render_footer
from app.web.components.header import render_header
from app.web.components.icons import ICON_ARROW_RIGHT, ICON_MAP_PIN
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles


def _fmt_price(v: int) -> str:
    return f"{v:,}".replace(",", " ") + " ₽"


def _deal_card_html(card: dict) -> str:
    """Предложение салона: окна и услуги идут от конкретных мастеров."""
    href = f"/salons/{card['salon_id']}"
    masters = tuple(
        (
            m["name"],
            m["specialization"] or "",
            # Окно ведёт на страницу салона: свободное время и запись — там.
            tuple(ui.slot(w, href=href) for w in m["windows"]),
            tuple(
                ui.service_line(
                    s["name"],
                    price=_fmt_price(s["new_price"]),
                    old_price=_fmt_price(s["old_price"]),
                )
                for s in m["services"]
            ),
        )
        for m in card["masters"]
    )
    return ui.deal_card(
        salon_id=card["salon_id"],
        name=card["salon_name"],
        href=href,
        address=card["address"] or "",
        discount_label=f"Скидка −{card['discount_percent']}%",
        masters=masters,
        action_icon=ICON_ARROW_RIGHT,
    )


async def render_evening_deals_page(db: AsyncSession, city: str = None, user=None) -> str:
    feed = await build_feed(db, city)
    cities = feed["cities"]
    selected = feed["selected_city"]
    cards = feed["cards"]

    city_options = '<option value="">Все города</option>'
    for c in cities:
        sel = " selected" if selected and c.lower() == selected.lower() else ""
        city_options += f'<option value="{e(c)}"{sel}>{e(c)}</option>'

    # Тот же выбор города, что в каталоге (.city-select-wrapper): фильтр
    # должен выглядеть и вести себя одинаково на обеих страницах.
    city_selector = f"""
    <form method="get" class="evening-filter">
        <div class="city-select-wrapper">
            {ICON_MAP_PIN}
            <select id="eveningCity" name="city" class="city-select custom-select"
                    aria-label="Город" onchange="this.form.submit()">
                {city_options}
            </select>
        </div>
        <noscript>{ui.button("Показать", kind="secondary", type_="submit")}</noscript>
    </form>
    """

    if cards:
        body = '<div class="r-salon-grid">' + "".join(_deal_card_html(c) for c in cards) + "</div>"
    else:
        # Пустая подборка — обычное дело (окна бывают не каждый день), поэтому
        # из неё есть выход: в каталог, где запись доступна и без скидки.
        body = ui.empty_state(
            "Сегодня свободных вечерних окон со скидкой нет",
            text="Подборка обновляется каждый день. Записаться можно и без скидки — "
                 "в каталоге есть свободное время.",
            action_label="Смотреть каталог",
            action_href="/salons",
        )

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <title>Вечерние окна со скидкой — руми</title>
    <meta name="description" content="Свободные вечерние окна в салонах красоты со скидкой — запишитесь на сегодня.">
    {get_base_styles()}
</head>
<body class="page-body">
    {render_header("evening")}
    {render_sidebar("evening", user)}
    <main class="main-content cabinet-main evening-main">
        <div class="section-container">
            <header class="cabinet-head">
                <h1 class="r-display">Вечерние окна со скидкой</h1>
                <p class="r-text r-muted">Свободное время на сегодня вечером. Скидка
                    применяется сама, когда вы записываетесь на такое окно.</p>
            </header>
            {city_selector}
            {body}
        </div>
        {render_footer(user)}
    </main>
</body>
</html>"""
