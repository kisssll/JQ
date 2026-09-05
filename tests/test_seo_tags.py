# tests/test_seo_tags.py
"""canonical, Open Graph и ответ на HEAD — то, что должно быть на каждой
странице, а не на тех, где не забыли дописать."""
import re

import pytest

PAGES = ["/", "/salons", "/tariffs", "/about", "/business", "/legal", "/cookies"]


def _meta(html: str, prop: str) -> str | None:
    m = re.search(rf'<meta property="{prop}" content="(.*?)">', html)
    return m.group(1) if m else None


@pytest.mark.parametrize("path", PAGES)
async def test_every_page_has_canonical_and_open_graph(client, path):
    r = await client.get(path)
    assert r.status_code == 200
    assert 'rel="canonical"' in r.text, path
    assert _meta(r.text, "og:title"), path
    assert _meta(r.text, "og:image"), path


async def test_canonical_drops_query_parameters(client):
    """Каталог открывается с ?q=/?page=; без этого поисковик считает их
    разными страницами и делит между ними вес."""
    r = await client.get("/salons?q=маникюр&page=2")
    assert 'rel="canonical" href="https://rrumi.ru/salons"' in r.text


async def test_page_keeps_its_own_canonical(client):
    """Главная объявляет canonical сама — второго быть не должно."""
    r = await client.get("/")
    assert r.text.count('rel="canonical"') == 1


async def test_open_graph_takes_the_page_title(client):
    r = await client.get("/tariffs")
    title = re.search(r"<title>(.*?)</title>", r.text, re.S).group(1).strip()
    assert _meta(r.text, "og:title") == title


async def test_attribute_values_are_escaped():
    """Заголовок страницы салона собран из названий услуг — из
    пользовательского ввода. Кавычка в нём не должна ломать разметку."""
    from app.web.seo_middleware import build_tags
    page = '<html><head><title>Мастер "Ёлка" &amp; Ко</title></head><body></body></html>'
    tags = build_tags("/salons/1", page)
    assert 'content="Мастер &quot;Ёлка&quot; &amp; Ко"' in tags


async def test_non_html_responses_are_untouched(client):
    for path, marker in (("/sitemap.xml", "<urlset"), ("/robots.txt", "User-agent")):
        r = await client.get(path)
        assert r.status_code == 200
        assert marker in r.text
        assert "og:title" not in r.text, path


async def test_error_pages_get_no_canonical(client):
    r = await client.get("/такой-страницы-нет")
    assert r.status_code == 404
    assert 'rel="canonical"' not in r.text


# ── HEAD ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/", "/health", "/robots.txt", "/salons"])
async def test_head_is_answered_like_get(client, path):
    """FastAPI не добавляет HEAD к маршрутам с GET, и весь сайт отвечал 405.
    По HEAD ходят проверки доступности и часть ботов превью."""
    head = await client.head(path)
    get = await client.get(path)
    assert head.status_code == get.status_code == 200, path
    assert head.content == b"", path
    # Content-Length остаётся от GET — так требует RFC 9110.
    assert head.headers.get("content-length") == get.headers.get("content-length"), path


async def test_head_keeps_the_security_headers(client):
    r = await client.head("/")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in r.headers
