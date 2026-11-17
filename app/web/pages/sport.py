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
