# app/web/seo_middleware.py
"""Теги, которые должны быть на КАЖДОЙ странице: canonical и Open Graph.

Страницы собираются двумя десятками отдельных функций, у каждой свой <head>.
Дописывать в них теги руками — значит гарантированно забыть про половину и
разъехаться при первой же новой странице. Поэтому теги дописываются здесь,
одним местом, из того, что страница уже про себя сообщила: <title> и
<meta name="description">.

canonical нужен потому, что каталог открывается с разными параметрами
(?q=, ?page=, ?city=), и без него поисковик считает их разными страницами и
делит между ними вес. Указываем адрес без параметров — все варианты
схлопываются в один.

Open Graph отвечает за то, как выглядит ссылка на сайт в Телеграме, ВК и
мессенджерах. Без него превью либо пустое, либо собрано наугад.
"""
from __future__ import annotations

import html as html_mod
import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.config import settings

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_DESC_RE = re.compile(
    r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']\s*/?>', re.S | re.I
)

SITE_NAME = "Руми"
# Квадратный PNG: webp в превью показывают не все клиенты, а логотип узнаётся
# лучше, чем декоративное фото с главной.
OG_IMAGE = "/static/icons/icon-512.png"
FALLBACK_DESCRIPTION = (
    "Руми — онлайн-запись в салоны красоты и к частным мастерам без звонков."
)


def _attr(value: str) -> str:
    """Текст из документа — в значение атрибута.

    Сначала распаковываем сущности, потом экранируем заново: заголовок
    страницы салона собран из названий услуг, то есть из пользовательского
    ввода, и перенос его «как есть» в content="..." ломал бы разметку.
    """
    return html_mod.escape(html_mod.unescape(value).strip(), quote=True)


def build_tags(path: str, page_html: str) -> str:
    canonical = f"{settings.PUBLIC_BASE_URL.rstrip('/')}{path}"

    title_match = _TITLE_RE.search(page_html)
    title = _attr(title_match.group(1)) if title_match else SITE_NAME

    desc_match = _DESC_RE.search(page_html)
    description = _attr(desc_match.group(1)) if desc_match else _attr(FALLBACK_DESCRIPTION)

    image = f"{settings.PUBLIC_BASE_URL.rstrip('/')}{OG_IMAGE}"
    return (
        f'<link rel="canonical" href="{html_mod.escape(canonical, quote=True)}">'
        f'<meta property="og:type" content="website">'
        f'<meta property="og:site_name" content="{SITE_NAME}">'
        f'<meta property="og:locale" content="ru_RU">'
        f'<meta property="og:title" content="{title}">'
        f'<meta property="og:description" content="{description}">'
        f'<meta property="og:url" content="{html_mod.escape(canonical, quote=True)}">'
        f'<meta property="og:image" content="{image}">'
        f'<meta name="twitter:card" content="summary">'
    )


class SeoTagsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)

        # Только успешные HTML-страницы: у 404 canonical не нужен, а для
        # JSON/XML/картинок теги бессмысленны.
        if response.status_code != 200:
            return response
        if not response.headers.get("content-type", "").startswith("text/html"):
            return response

        raw = b"".join([chunk async for chunk in response.body_iterator])
        try:
            page = raw.decode("utf-8")
        except UnicodeDecodeError:
            return Response(content=raw, status_code=response.status_code,
                            headers=dict(response.headers))

        # Единственный источник canonical и Open Graph — этот middleware:
        # у страниц своих таких тегов быть не должно. Проверка защищает от
        # повторной обработки, а не разрешает странице объявить их самой.
        if "</head>" in page and "og:title" not in page:
            page = page.replace("</head>", build_tags(request.url.path, page) + "</head>", 1)

        headers = dict(response.headers)
        headers.pop("content-length", None)   # длина изменилась
        return Response(content=page, status_code=response.status_code,
                        headers=headers, media_type=response.media_type)


class HeadRequestMiddleware:
    """Отвечает на HEAD так же, как на GET, но без тела.

    FastAPI, в отличие от Starlette, не добавляет HEAD к маршрутам с GET —
    и весь сайт отвечал на HEAD кодом 405. По нему ходят проверки доступности
    и часть ботов, собирающих превью ссылок: для них сайт выглядел сломанным.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("method") != "HEAD":
            return await self.app(scope, receive, send)

        scope = dict(scope)
        scope["method"] = "GET"
        finished = False

        async def send_without_body(message):
            nonlocal finished
            if message["type"] != "http.response.body":
                return await send(message)
            if finished:
                # Тело уже закрыли на первом куске — остальные глотаем,
                # иначе ASGI-сервер получит данные после конца ответа.
                return
            finished = True
            # Content-Length остаётся от GET — так и требует RFC 9110.
            await send({"type": "http.response.body", "body": b"", "more_body": False})

        await self.app(scope, receive, send_without_body)
