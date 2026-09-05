# tests/test_site_verification.py
"""Файлы подтверждения прав на сайт (Яндекс.Вебмастер и т. п.)."""
import pytest


TOKEN = "dc164c9587b875b2"
FILENAME = f"yandex_{TOKEN}.html"


async def test_verification_file_is_served(client):
    r = await client.get(f"/{FILENAME}")
    assert r.status_code == 200
    # Панель ищет в теле именно эту строку.
    assert f"Verification: {TOKEN}" in r.text
    assert r.headers["content-type"].startswith("text/html")


async def test_verification_file_is_not_wrapped_in_the_site_layout(client):
    """Отдаём файл как есть: панель сверяет содержимое, а не страницу сайта."""
    r = await client.get(f"/{FILENAME}")
    assert "<nav" not in r.text and "main-content" not in r.text
    assert r.text.strip().startswith("<html>")


@pytest.mark.parametrize("path", [
    "/yandex_deadbeefdeadbeef.html",   # чужой токен
    "/anything.html",
])
async def test_other_html_paths_stay_404(client, path):
    r = await client.get(path)
    assert r.status_code == 404


async def test_route_does_not_shadow_the_other_root_files(client):
    """Маршрут стоит раньше catch-all — важно, чтобы он не перехватил
    robots.txt и карту сайта."""
    for path in ("/robots.txt", "/sitemap.xml"):
        r = await client.get(path)
        assert r.status_code == 200, path
