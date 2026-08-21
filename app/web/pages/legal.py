# app/web/pages/legal.py
"""Нормативные документы: пользовательское соглашение, политика обработки
персональных данных, согласие на обработку.

Тексты лежат отдельными HTML-файлами в app/web/legal/ — так их правит юрист,
не трогая Python. Отдаём их именно текстом (не картинкой и не PDF): ч.2 ст.18.1
152-ФЗ требует свободный доступ к Политике, а на практике это ещё и значит, что
текст должен быть доступен для копирования и поиска.
"""
import pathlib

from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles

_LEGAL_DIR = pathlib.Path(__file__).resolve().parent.parent / "legal"

# Редакция документов. Дата показывается на странице и уходит вместе с
# согласием в журнал (app/models/models.py::UserConsent), чтобы потом можно было
# сказать, с какой именно редакцией согласился человек.
LEGAL_VERSION = "2026-08-21"
LEGAL_VERSION_HUMAN = "21 августа 2026"

DOCUMENTS = {
    "terms": {
        "slug": "terms",
        "file": "terms.html",
        "title": "Пользовательское соглашение",
        "description": "Условия использования сервиса Руми: регистрация, записи, права и обязанности сторон.",
    },
    "privacy": {
        "slug": "privacy",
        "file": "privacy.html",
        "title": "Политика обработки персональных данных",
        "description": "Какие данные Руми собирает, зачем, как хранит и как их удалить.",
    },
    "consent": {
        "slug": "consent",
        "file": "consent.html",
        "title": "Согласие на обработку персональных данных",
        "description": "Текст согласия, которое подтверждается отметкой при регистрации и записи.",
    },
}

_cache: dict[str, str] = {}


def _body(slug: str) -> str:
    if slug not in _cache:
        _cache[slug] = (_LEGAL_DIR / DOCUMENTS[slug]["file"]).read_text(encoding="utf-8")
    return _cache[slug]


def _other_links(current: str) -> str:
    items = "".join(
        f'<li><a class="legal-nav-link" href="/{d["slug"]}">{d["title"]}</a></li>'
        for slug, d in DOCUMENTS.items() if slug != current
    )
    return f'<ul class="legal-nav-list">{items}</ul>'


def render_legal_page(slug: str, user=None) -> str:
    doc = DOCUMENTS[slug]
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{doc['title']} | руми.</title>
    <meta name="description" content="{doc['description']}">
    {get_base_styles()}
</head>
<body>
    {render_header("legal")}
    {render_sidebar("legal", user)}

    <main class="main-content legal-main">
        <div class="section-container legal-container">
            <article class="legal-doc">
                <p class="legal-eyebrow">Документы</p>
                <h1 class="legal-title">{doc['title']}</h1>
                <p class="legal-version">Редакция от {LEGAL_VERSION_HUMAN}</p>
                <div class="legal-body">
{_body(slug)}
                </div>
            </article>

            <aside class="legal-aside">
                <h2 class="legal-aside-title">Другие документы</h2>
                {_other_links(slug)}
                <div class="legal-operator">
                    <p class="legal-operator-title">Оператор персональных данных</p>
                    <p>ООО «РУМИ»</p>
                    <p>634021, Томская обл., г. Томск,<br>ул. Шевченко, д. 21, кв. 20</p>
                    <p>ОГРН 1267000004370 · ИНН 7000036144</p>
                    <p><a class="text-link" href="mailto:hello@rrumi.ru">hello@rrumi.ru</a></p>
                </div>
            </aside>
        </div>
        {render_footer(user)}
    </main>
</body>
</html>"""
