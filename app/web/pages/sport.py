import html

from app.web.components.styles import get_base_styles
from app.models.sport import SportOrganization
from app.web.pages.legal import LEGAL_VERSION


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


def render_sparta_app(
    slug: str = "sparta",
    name: str = "Спарта Плюс",
    city: str = "",
    logo_url: str | None = None,
) -> str:
    safe_slug = html.escape(slug, quote=True)
    safe_name = html.escape(name)
    safe_name_attr = html.escape(name, quote=True)
    safe_city_attr = html.escape(city, quote=True)
    safe_logo_attr = html.escape(logo_url or "", quote=True)
    favicon = (
        '<link rel="icon" href="/static/sport/sparta/sparta-logo.png">'
        if slug == "sparta"
        else ""
    )
    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="description" content="{safe_name} — спортивный клуб на Руми">
    <meta name="theme-color" content="#ffffff">
    <meta name="consent-version" content="{LEGAL_VERSION}">
    <title>{safe_name} — Руми Спорт</title>
    {favicon}
    <link rel="stylesheet" href="/static/dist/sport-sparta.css">
</head>
<body>
    <div id="root" data-gym-slug="{safe_slug}" data-gym-name="{safe_name_attr}" data-gym-city="{safe_city_attr}" data-gym-logo="{safe_logo_attr}"></div>
    <script type="module" src="/static/dist/sport-sparta.js"></script>
</body>
</html>"""
