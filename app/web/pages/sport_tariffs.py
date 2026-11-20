import html

from app.models.sport import SportMembershipPlan, SportOrganization
from app.web.components.footer import render_footer
from app.web.components.header import render_header
from app.web.components.styles import get_base_styles


def _plan_card(plan: SportMembershipPlan, organization: SportOrganization) -> str:
    if plan.price:
        price = f"{plan.price:,}".replace(",", " ") + " ₽"
    elif "уточн" in (plan.unit or "").lower():
        price = "Стоимость уточняется"
    else:
        price = "Бесплатно"

    details = "".join(
        f"<li>{html.escape(item)}</li>" for item in (plan.items or [])
    )
    if not details and plan.unit:
        details = f"<li>{html.escape(plan.unit)}</li>"

    return f"""
        <article class="sport-tariff-card">
            <p class="sport-tariff-card__club">{html.escape(organization.name)} · {html.escape(organization.city)}</p>
            <h2>{html.escape(plan.name)}</h2>
            <p class="sport-tariff-card__price">{price}</p>
            <ul>{details}</ul>
            <a href="/sport/{html.escape(organization.slug, quote=True)}/prices">Подробнее о клубе и абонементах</a>
        </article>"""


def render_sport_tariffs_page(
    user=None,
    plans: list[tuple[SportMembershipPlan, SportOrganization]] | None = None,
) -> str:
    cards = "".join(_plan_card(plan, organization) for plan, organization in plans or [])
    if not cards:
        cards = """
            <p class="sport-tariffs__empty">
                Пока нет опубликованных тарифов. Посмотрите спортивные клубы или вернитесь позже.
                <a href="/sport/">Перейти к клубам</a>
            </p>"""

    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Тарифы спортивных клубов — Руми Спорт</title>
    <meta name="description" content="Абонементы и предложения спортивных клубов на Руми Спорт.">
    {get_base_styles()}
    <style>
        .sport-tariffs{{max-width:1120px;margin:48px auto;padding:0 20px 72px}}
        .sport-tariffs__intro{{max-width:700px;margin-bottom:32px}}
        .sport-tariffs__intro p{{color:#666;line-height:1.6}}
        .sport-tariffs__grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:18px}}
        .sport-tariff-card{{padding:22px;border:1px solid #ddd;background:#fff}}
        .sport-tariff-card__club{{color:#666;font-size:14px}}
        .sport-tariff-card__price{{font-size:24px;font-weight:700}}
        .sport-tariff-card ul{{padding-left:20px;line-height:1.7}}
        .sport-tariff-card a,.sport-tariffs__empty a{{color:inherit}}
    </style>
</head>
<body>
    {render_header("sport_tariffs", user)}
    <main class="sport-tariffs">
        <section class="sport-tariffs__intro">
            <h1>Тарифы спортивных клубов</h1>
            <p>Условия и стоимость абонементов устанавливает каждый клуб. Выберите предложение,
            чтобы посмотреть информацию о клубе и записаться.</p>
        </section>
        <section class="sport-tariffs__grid" aria-label="Абонементы спортивных клубов">
            {cards}
        </section>
    </main>
    {render_footer(user)}
</body>
</html>"""
