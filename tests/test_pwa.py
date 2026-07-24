# tests/test_pwa.py
"""PWA: manifest, service worker, офлайн-страница, иконки."""
import json
import os


async def test_manifest(client):
    r = await client.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert "manifest" in r.headers["content-type"]
    data = json.loads(r.text)
    assert data["name"].startswith("Руми")
    assert data["display"] == "standalone"
    assert data["start_url"] == "/"
    sizes = {i["sizes"] for i in data["icons"]}
    assert "192x192" in sizes and "512x512" in sizes
    assert any(i.get("purpose") == "maskable" for i in data["icons"])


async def test_service_worker(client):
    r = await client.get("/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert r.headers.get("cache-control") == "no-cache"
    assert "addEventListener('fetch'" in r.text  # network-first fetch-хендлер (для установки)


async def test_offline_page(client):
    r = await client.get("/offline")
    assert r.status_code == 200
    assert "Нет подключения" in r.text


def test_icons_exist():
    for name in ("icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png"):
        p = os.path.join("static", "icons", name)
        assert os.path.exists(p) and os.path.getsize(p) > 500, p
