# app/web/pages/evening_deals.py
"""Публичная страница-подборка «Вечерние окна со скидкой».

Салоны и мастера, у которых сегодня есть свободные вечерние слоты со скидкой.
Скидка применяется автоматически при записи на такой слот (см.
evening_deals_service.evening_deal_discount + create_booking)."""
import html

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.evening_deals_service import build_feed
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.components.icons import ICON_MAP_PIN, ICON_ARROW_RIGHT


def _fmt_price(v: int) -> str:
    return f"{v:,}".replace(",", " ")


async def render_evening_deals_page(db: AsyncSession, city: str = None, user=None) -> str:
    feed = await build_feed(db, city)
    cities = feed["cities"]
    selected = feed["selected_city"]
    cards = feed["cards"]

    city_options = '<option value="">Все города</option>'
    for c in cities:
        sel = " selected" if selected and c.lower() == selected.lower() else ""
        city_options += f'<option value="{html.escape(c, quote=True)}"{sel}>{html.escape(c)}</option>'

    city_selector = f"""
    <form method="get" class="evening-city-form">
        <label class="evening-city-label">Город:</label>
        <select name="city" class="custom-select" onchange="this.form.submit()">
            {city_options}
        </select>
    </form>
    """

    cards_html = ""
    for card in cards:
        masters_html = ""
        for m in card["masters"]:
            windows = " ".join(
                f'<span class="evening-slot">{w}</span>' for w in m["windows"]
            )
            svc_rows = ""
            for s in m["services"]:
                svc_rows += f"""
                <div class="evening-svc">
                    <span class="evening-svc-name">{html.escape(s['name'])}</span>
                    <span class="evening-svc-price">
                        <s>{_fmt_price(s['old_price'])} ₽</s>
                        <b>{_fmt_price(s['new_price'])} ₽</b>
                    </span>
                </div>"""
            masters_html += f"""
            <div class="evening-master">
                <div class="evening-master-head">
                    <span class="evening-master-name">{html.escape(m['name'])}</span>
                    <span class="evening-master-spec">{html.escape(m['specialization'] or '')}</span>
                </div>
                <div class="evening-slots">Свободно вечером: {windows}</div>
                <div class="evening-svc-list">{svc_rows}</div>
            </div>"""

        cards_html += f"""
        <div class="evening-card">
            <div class="evening-card-head">
                <div>
                    <h3 class="evening-salon-name">{html.escape(card['salon_name'])}</h3>
                    <p class="evening-salon-addr">{ICON_MAP_PIN} {html.escape(card['address'] or '')}</p>
                </div>
                <span class="evening-badge">−{card['discount_percent']}%</span>
            </div>
            {masters_html}
            <a href="/salons/{card['salon_id']}" class="btn-primary evening-book-btn">
                Записаться со скидкой {ICON_ARROW_RIGHT}
            </a>
        </div>"""

    if not cards_html:
        cards_html = """
        <div class="evening-empty">
            <p class="text-muted">Сегодня свободных вечерних окон со скидкой нет.
            Загляните завтра — подборка обновляется каждый день.</p>
        </div>"""

    extra_css = """
    <style>
    .evening-hero{text-align:center}
    .evening-city-form{display:flex;align-items:center;gap:.6rem;justify-content:center;margin:1rem 0}
    .evening-city-label{font-weight:600}
    .evening-grid{display:grid;gap:1.2rem;grid-template-columns:repeat(auto-fill,minmax(320px,1fr))}
    .evening-card{background:var(--color-surface,#fff);border:1px solid var(--color-border,#eee);border-radius:1rem;padding:1.2rem;display:flex;flex-direction:column;gap:.8rem}
    .evening-card-head{display:flex;justify-content:space-between;align-items:flex-start;gap:.5rem}
    .evening-salon-name{margin:0;font-size:1.1rem}
    .evening-salon-addr{margin:.2rem 0 0;color:var(--color-muted,#888);font-size:.85rem}
    .evening-badge{background:#16a34a;color:#fff;font-weight:700;padding:.3rem .6rem;border-radius:.6rem;white-space:nowrap}
    .evening-master{border-top:1px solid var(--color-border,#eee);padding-top:.7rem}
    .evening-master-head{display:flex;justify-content:space-between;gap:.5rem;flex-wrap:wrap}
    .evening-master-name{font-weight:600}
    .evening-master-spec{color:var(--color-muted,#888);font-size:.85rem}
    .evening-slots{margin:.4rem 0;font-size:.85rem;color:var(--color-muted,#666)}
    .evening-slot{display:inline-block;background:var(--color-accent-light,#f3e8ff);color:#6b21a8;border-radius:.4rem;padding:.1rem .5rem;margin:.1rem}
    .evening-svc{display:flex;justify-content:space-between;gap:.5rem;padding:.2rem 0;font-size:.9rem}
    .evening-svc-price s{color:var(--color-muted,#999);margin-right:.4rem}
    .evening-svc-price b{color:#16a34a}
    .evening-book-btn{margin-top:auto;text-align:center}
    .evening-empty{padding:3rem;text-align:center}
    </style>
    """

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Вечерние окна со скидкой — руми</title>
    <meta name="description" content="Свободные вечерние слоты в салонах красоты со скидкой — успейте записаться сегодня.">
    {get_base_styles()}
    {extra_css}
</head>
<body>
    {render_header("evening")}
    {render_sidebar("evening", user)}
    <main class="main-content">
        <section class="section-py bg-surface-alt evening-hero">
            <div class="section-container">
                <h1 class="text-display">🌙 Вечерние окна со скидкой</h1>
                <p class="text-body-lg">Свободные вечерние слоты на сегодня — успейте записаться дешевле</p>
                {city_selector}
            </div>
        </section>
        <section class="section-py bg-surface">
            <div class="section-container">
                <div class="evening-grid">
                    {cards_html}
                </div>
            </div>
        </section>
        {render_footer(user)}
    </main>
</body>
</html>"""
