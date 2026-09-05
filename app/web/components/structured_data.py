# app/web/components/structured_data.py
"""Разметка Schema.org (JSON-LD) для поисковых систем.

Зачем: по запросу «руми» поисковику неоткуда узнать, что «Руми», «Rumi» и
ООО «РУМИ» с ИНН 7000036144 — одно и то же, и что этому бренду принадлежит
rrumi.ru. Название в <title> такой связи не даёт: слово «руми» в выдаче прочно
занято персидским поэтом. Разметка заявляет бренд явно — с юрлицом, адресом и
написаниями-синонимами.

Отдаётся только на главной. Дублировать организацию на каждой странице не надо:
робот берёт её один раз с корня сайта, а лишние копии только раздувают HTML.
"""
import json

# Написания, по которым нас могут искать. Домен с двойной «r» точного
# совпадения с брендом не даёт, поэтому синонимы перечисляем явно.
_ALIASES = ["Rumi", "РУМИ", "руми", "rrumi", "Руми — салоны красоты"]

_ORGANIZATION = {
    "@type": "Organization",
    "@id": "https://rrumi.ru/#organization",
    "name": "Руми",
    "alternateName": _ALIASES,
    "legalName": "Общество с ограниченной ответственностью «РУМИ»",
    "url": "https://rrumi.ru/",
    "logo": {
        "@type": "ImageObject",
        "url": "https://rrumi.ru/static/images/rumi-logo.webp",
    },
    "email": "hello@rrumi.ru",
    "taxID": "7000036144",          # ИНН
    "vatID": "1267000004370",       # ОГРН
    "address": {
        "@type": "PostalAddress",
        "streetAddress": "ул. Шевченко, д. 21, кв. 20",
        "addressLocality": "Томск",
        "addressRegion": "Томская область",
        "postalCode": "634021",
        "addressCountry": "RU",
    },
    "areaServed": {"@type": "Country", "name": "Россия"},
    # Официальные представительства. Именно так поисковик склеивает
    # разрозненные упоминания бренда в одну сущность.
    "sameAs": [
        "https://vk.ru/rrumii",
        "https://vk.com/rrumii",
        "https://t.me/rrumii",
    ],
    "description": (
        "Руми — сервис онлайн-записи в салоны красоты и к частным мастерам: "
        "поиск мастера, запись без звонков, напоминания и панель управления "
        "для салонов."
    ),
}

_WEBSITE = {
    "@type": "WebSite",
    "@id": "https://rrumi.ru/#website",
    "name": "Руми",
    "alternateName": _ALIASES,
    "url": "https://rrumi.ru/",
    "inLanguage": "ru-RU",
    "publisher": {"@id": "https://rrumi.ru/#organization"},
    # Поисковая строка сайта: поисковик может показать её прямо в выдаче.
    # Цель ведёт на реальный параметр каталога — /salons?q=…
    "potentialAction": {
        "@type": "SearchAction",
        "target": {
            "@type": "EntryPoint",
            "urlTemplate": "https://rrumi.ru/salons?q={search_term_string}",
        },
        "query-input": "required name=search_term_string",
    },
}


def render_site_schema() -> str:
    """Блок JSON-LD с организацией и сайтом. Только для главной страницы."""
    payload = {"@context": "https://schema.org", "@graph": [_ORGANIZATION, _WEBSITE]}
    # ensure_ascii=False — кириллица должна остаться читаемой; </ экранируем,
    # иначе строка вида "</script>" в данных закрыла бы тег раньше времени.
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    body = body.replace("</", "<\\/")
    return f'<script type="application/ld+json">{body}</script>'
