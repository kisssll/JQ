import html
import json
from urllib.parse import quote

from app.core.config import settings
from app.web.components.styles import _asset_version, get_base_styles
from app.models.sport import SportOrganization
from app.web.pages.legal import LEGAL_VERSION


_SPARTA_CSS = _asset_version("sport-sparta.css")
_SPARTA_JS = _asset_version("sport-sparta.js")


def _sport_meta_description(name: str, city: str, description: str) -> str:
    summary = " ".join((description or "").split())
    prefix = f"{name} · {city}" if city else name
    text = f"{prefix}. {summary}" if summary else (
        f"{prefix} — спортивный клуб: направления, расписание и онлайн-запись."
    )
    if len(text) > 160:
        truncated = text[:157]
        boundary = truncated.rfind(" ")
        if boundary > 120:
            truncated = truncated[:boundary]
        text = truncated.rstrip(" ,.;:") + "…"
    return html.escape(text, quote=True)


def _sport_organization_schema(
    slug: str,
    name: str,
    city: str,
    address: str,
    description: str,
    venues: list | None = None,
) -> str:
    organization: dict[str, object] = {
        "@context": "https://schema.org",
        "@type": "SportsOrganization",
        "name": name,
        "url": f"{settings.PUBLIC_BASE_URL.rstrip('/')}/sport/{quote(slug, safe='')}",
        "description": description,
    }
    if venues:
        sub_locations = []
        for v in venues:
            loc = {
                "@type": "SportsClub",
                "name": getattr(v, "name", "") or name,
                "address": {
                    "@type": "PostalAddress",
                    "addressCountry": "RU",
                    "addressLocality": getattr(v, "city", "") or city,
                    "streetAddress": getattr(v, "address", ""),
                }
            }
            sub_locations.append(loc)
        organization["subOrganization"] = sub_locations
    elif city or address:
        location: dict[str, str] = {
            "@type": "PostalAddress",
            "addressCountry": "RU",
        }
        if city:
            location["addressLocality"] = city
        if address:
            location["streetAddress"] = address
        organization["address"] = location

    body = json.dumps(organization, ensure_ascii=False, separators=(",", ":"))
    body = body.replace("</", "<\\/")
    return f'<script type="application/ld+json">{body}</script>'


def render_sport_placeholder(organization: SportOrganization) -> str:
    return render_sport_gym_template(
        slug=organization.slug,
        name=organization.name,
        city=organization.city or "",
        logo_url=organization.logo_url,
        description=organization.description or "",
        address=organization.address or "",
    )


def render_sport_gym_template(
    slug: str = "club",
    name: str = "Спортивный клуб",
    city: str = "",
    logo_url: str | None = None,
    description: str = "",
    address: str = "",
    venues: list | None = None,
    coaches: list | None = None,
    disciplines: list | None = None,
    plans: list | None = None,
    gallery: list | None = None,
) -> str:
    if slug == "sparta":
        name = "СПАРТА"
    safe_slug = html.escape(slug, quote=True)
    safe_name = html.escape(name)
    safe_name_attr = html.escape(name, quote=True)
    safe_city_attr = html.escape(city, quote=True)
    safe_logo_attr = html.escape(logo_url or "", quote=True)
    title = f"{name} · {city}" if city else name
    if len(title) > 55:
        title_prefix = title[:52]
        boundary = title_prefix.rfind(" ")
        if boundary > 35:
            title_prefix = title_prefix[:boundary]
        title = title_prefix.rstrip(" ·") + "…"
    safe_title = html.escape(f"{title} | Руми Спорт")
    meta_description = _sport_meta_description(name, city, description)
    schema = _sport_organization_schema(
        slug,
        name,
        city,
        address,
        description or f"{name} — спортивный клуб в {city} на Руми Спорт.",
        venues=venues,
    )
    if logo_url:
        favicon = f'<link rel="icon" href="{html.escape(logo_url, quote=True)}">'
    elif slug == "sparta":
        favicon = '<link rel="icon" href="/static/sport/sparta/sparta-logo.png">'
    else:
        favicon = '<link rel="icon" href="/static/icons/favicon.ico">'

    # SSR skeleton / initial markup for SEO, accessibility and smooth hydration
    ssr_parts = [
        '<div class="sport-gym-ssr" style="display:none;" aria-hidden="true">',
        f'<h1>{safe_name}</h1>',
    ]
    if city:
        ssr_parts.append(f'<p class="city">{html.escape(city)}</p>')
    if description:
        ssr_parts.append(f'<p class="desc">{html.escape(description)}</p>')
    if venues:
        ssr_parts.append('<div class="venues">')
        for v in venues:
            v_name = html.escape(getattr(v, "name", "") or "")
            v_addr = html.escape(getattr(v, "address", "") or "")
            ssr_parts.append(f'<div class="venue-item"><strong>{v_name}</strong>: {v_addr}</div>')
        ssr_parts.append('</div>')
    if disciplines:
        ssr_parts.append('<div class="disciplines">')
        for d in disciplines:
            d_name = html.escape(getattr(d, "name", "") or "")
            ssr_parts.append(f'<span class="discipline-tag">{d_name}</span>')
        ssr_parts.append('</div>')
    ssr_parts.append('</div>')
    ssr_markup = "".join(ssr_parts)

    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="description" content="{meta_description}">
    <meta name="theme-color" content="#ffffff">
    <meta name="consent-version" content="{LEGAL_VERSION}">
    <title>{safe_title}</title>
    {schema}
    {favicon}
    <link rel="stylesheet" href="/static/dist/sport-sparta.css?v={_SPARTA_CSS}">
</head>
<body>
    <div id="root" data-gym-slug="{safe_slug}" data-gym-name="{safe_name_attr}" data-gym-city="{safe_city_attr}" data-gym-logo="{safe_logo_attr}">{ssr_markup}</div>
    <script type="module" src="/static/dist/sport-sparta.js?v={_SPARTA_JS}"></script>
</body>
</html>"""


# Backward compatibility alias
render_sparta_app = render_sport_gym_template
