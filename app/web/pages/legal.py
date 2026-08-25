# app/web/pages/legal.py
"""Нормативные документы: пользовательское соглашение, политика обработки
персональных данных, согласие на обработку.

Тексты лежат отдельными HTML-файлами в app/web/legal/ — так их правит юрист,
не трогая Python. Отдаём их именно текстом (не картинкой и не PDF): ч.2 ст.18.1
152-ФЗ требует свободный доступ к Политике, а на практике это ещё и значит, что
текст должен быть доступен для копирования и поиска.
"""
from app.web.components.escaping import e
import pathlib
import re

from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles

_LEGAL_DIR = pathlib.Path(__file__).resolve().parent.parent / "legal"

# Редакция документов. Дата показывается на странице и уходит вместе с
# согласием в журнал (app/models/models.py::UserConsent), чтобы потом можно было
# сказать, с какой именно редакцией согласился человек.
LEGAL_VERSION = "2026-08-18"
LEGAL_VERSION_HUMAN = "18 августа 2026"

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
    "offer": {
        "slug": "offer",
        "file": "offer.html",
        "title": "Договор-оферта на оказание информационных услуг с использованием Сервиса «РУМИ»",
        "description": "Условия для клиентов: доступ к сервису, абонентская плата, расчёты и возвраты.",
    },
    "license": {
        "slug": "license",
        "file": "license.html",
        "title": "Лицензионный договор-оферта на использование Сервиса «РУМИ»",
        "description": "Условия для салонов и мастеров: лицензия на бизнес-панель и лицензионное вознаграждение.",
    },
    "cookies": {
        "slug": "cookies",
        "file": "cookies.html",
        "title": "Политика использования файлов cookie на сайте rrumi.ru",
        "description": "Какие файлы cookie ставит сайт, зачем они нужны и как ими управлять.",
    },
}

_cache: dict[str, str] = {}


def _strip_own_title(body: str, page_title: str) -> str:
    """Документ начинается собственным названием, и на странице оно дублировало
    <h1>. Срезаем ведущие заголовки, только если их текст целиком входит в
    название страницы — так «СОГЛАСИЕ» и «на обработку персональных данных»
    (в исходнике это две строки) уходят, а любой содержательный раздел
    остаётся. Файлы в app/web/legal/ при этом не трогаем: они верны оригиналу.
    """
    def norm(s: str) -> str:
        s = re.sub(r"<[^>]+>", "", s)
        s = re.sub(r"\s+", " ", s).strip().lower()
        return s.replace("руми", "").strip(" .«»")

    title = norm(page_title)
    while True:
        m = re.match(r"\s*<(h2|p)>(.*?)</\1>\s*", body, re.S)
        if not m:
            return body
        head = norm(m.group(2))
        # Совпадение в любую сторону: в документах название длиннее страницы
        # («Политика обработки персональных данных РУМИ»), а у согласия —
        # короче, оно разбито на две строки. Ограничение по длине обязательно:
        # без него условие «title in head» срезало пункт 1.1 Политики, который
        # просто упоминает название документа внутри себя.
        if not head or len(head) > len(title) + 12:
            return body
        if not (head in title or title in head):
            return body
        body = body[m.end():]


def _body(slug: str) -> str:
    if slug not in _cache:
        raw = (_LEGAL_DIR / DOCUMENTS[slug]["file"]).read_text(encoding="utf-8")
        _cache[slug] = _strip_own_title(raw, DOCUMENTS[slug]["title"])
    return _cache[slug]


def _other_links(current: str) -> str:
    items = "".join(
        f'<li><a class="legal-nav-link" href="/{d["slug"]}">{e(d["title"])}</a></li>'
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
    <title>{e(doc['title'])} | руми.</title>
    <meta name="description" content="{e(doc['description'])}">
    {get_base_styles()}
</head>
<body>
    {render_header("legal")}
    {render_sidebar("legal", user)}

    <main class="main-content legal-main">
        <div class="section-container legal-container">
            <article class="legal-doc">
                <p class="legal-eyebrow">Документы</p>
                <h1 class="legal-title">{e(doc['title'])}</h1>
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
