import html
from urllib.parse import quote

from app.web.components.styles import get_base_styles
from app.models.sport import SportOrganization
from app.web.pages.legal import LEGAL_VERSION


def render_sport_directory(organizations: list[SportOrganization]) -> str:
    cards = []
    for organization in organizations:
        name = html.escape(organization.name)
        city = html.escape(organization.city)
        description = html.escape(organization.description)
        href = "/sport/" + quote(organization.slug, safe="")
        logo = ""
        if organization.logo_url:
            logo = (
                f'<img src="{html.escape(organization.logo_url, quote=True)}" '
                f'alt="" width="72" height="72" loading="lazy">'
            )
        cards.append(
            f'<a class="sport-card" href="{html.escape(href, quote=True)}">'
            f'<div class="sport-logo">{logo}</div>'
            f'<div><p class="sport-city">{city}</p><h2>{name}</h2>'
            f'<p class="sport-description">{description}</p>'
            '<span class="sport-open">Открыть страницу →</span></div></a>'
        )

    content = "".join(cards) or '<p class="sport-empty">Организации скоро появятся.</p>'
    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Спортивные организации — Руми</title>
    <meta name="description" content="Каталог спортивных организаций на Руми">
    {get_base_styles()}
    <style>
        .sport-directory {{ max-width: 1120px; margin: 0 auto; padding: 64px 24px 96px; }}
        .sport-directory h1 {{ margin: 0 0 14px; font-size: clamp(2.2rem, 6vw, 4rem); }}
        .sport-lead {{ margin: 0 0 36px; color: var(--color-muted); }}
        .sport-list {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 18px; }}
        .sport-card {{ display: grid; grid-template-columns: 72px 1fr; gap: 18px; padding: 22px; border: 1px solid var(--color-border); border-radius: var(--radius-16); color: inherit; text-decoration: none; background: var(--color-surface); }}
        .sport-card:hover {{ border-color: var(--color-accent); }}
        .sport-logo {{ width: 72px; height: 72px; display: grid; place-items: center; overflow: hidden; border-radius: var(--radius-16); background: var(--color-surface-alt); }}
        .sport-logo img {{ width: 100%; height: 100%; object-fit: contain; }}
        .sport-city {{ margin: 0 0 5px; color: var(--color-muted); font-size: .85rem; }}
        .sport-card h2 {{ margin: 0 0 8px; font-size: 1.3rem; }}
        .sport-description {{ margin: 0 0 14px; color: var(--color-muted); line-height: 1.5; }}
        .sport-open {{ color: var(--color-accent-text); font-weight: 600; }}
        .sport-empty {{ padding: 28px; border-radius: var(--radius-16); background: var(--color-surface-alt); }}
    </style>
</head>
<body>
    <main class="sport-directory">
        <p class="eyebrow">Руми · Спорт</p>
        <h1>Спортивные организации</h1>
        <p class="sport-lead">Выберите клуб, чтобы посмотреть направления и расписание.</p>
        <section class="sport-list" aria-label="Список спортивных организаций">{content}</section>
    </main>
</body>
</html>"""


def render_sport_placeholder(organization: SportOrganization) -> str:
    name = html.escape(organization.name)
    city = html.escape(organization.city)
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} — Руми Спорт</title>{get_base_styles()}</head>
<body><main class="container" style="max-width:760px;margin:12vh auto;padding:24px">
<a href="/sport/">← Все спортивные организации</a>
<p class="eyebrow" style="margin-top:32px">{city}</p>
<h1>{name}</h1><p>Страница организации готовится.</p>
</main></body></html>"""


def render_sparta_app() -> str:
    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="description" content="Клуб боевого дзю-дзютцу «Спарта Плюс» в Томске">
    <meta name="theme-color" content="#ffffff">
    <meta name="consent-version" content="{LEGAL_VERSION}">
    <title>Спарта Плюс — Руми Спорт</title>
    <link rel="icon" href="/static/sport/sparta/sparta-logo.png">
    <link rel="stylesheet" href="/static/dist/sport-sparta.css">
</head>
<body>
    <div id="root"></div>
    <script type="module" src="/static/dist/sport-sparta.js"></script>
</body>
</html>"""
