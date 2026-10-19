# tests/test_footer_support.py
"""Три способа задать вопрос в подвале: почта, Telegram, MAX."""
import re

import pytest

from app.core.config import settings
from app.web.components.footer import render_footer, SUPPORT_EMAIL


@pytest.fixture()
def bots(monkeypatch):
    monkeypatch.setattr(settings, "TG_BOT_USERNAME", "rumi_beauty_bot")
    monkeypatch.setattr(settings, "MAX_BOT_USERNAME", "id7000036144_bot")
    monkeypatch.setattr(settings, "VK_GROUP_ID", 0)   # ВК проверяется в test_vk_bot.py


def _links(html: str) -> list[str]:
    return re.findall(r'class="footer-support-link" href="([^"]+)"', html)


def test_three_ways_to_ask(bots):
    hrefs = _links(render_footer())
    assert len(hrefs) == 3
    assert f"mailto:{SUPPORT_EMAIL}" in hrefs
    assert "https://t.me/rumi_beauty_bot?start=support" in hrefs
    assert "https://max.ru/id7000036144_bot?start=support" in hrefs


def test_bot_links_open_the_support_form_not_the_menu(bots):
    """Человек идёт по ссылке с вопросом. Лишний шаг через общее меню —
    потерянный вопрос, поэтому в ссылке метка support."""
    for href in _links(render_footer()):
        if href.startswith("http"):
            assert href.endswith("?start=support"), href


def test_bot_without_username_is_not_shown(monkeypatch):
    """Иначе ссылка вела бы на несуществующий адрес мессенджера."""
    monkeypatch.setattr(settings, "TG_BOT_USERNAME", "")
    monkeypatch.setattr(settings, "MAX_BOT_USERNAME", "")
    hrefs = _links(render_footer())
    assert hrefs == [f"mailto:{SUPPORT_EMAIL}"]


def test_username_at_sign_is_stripped(monkeypatch):
    """В окружении имя могут записать с собакой — в адресе её быть не должно."""
    monkeypatch.setattr(settings, "TG_BOT_USERNAME", "@rumi_beauty_bot")
    monkeypatch.setattr(settings, "MAX_BOT_USERNAME", "")
    assert "https://t.me/rumi_beauty_bot?start=support" in _links(render_footer())


def test_external_links_are_marked_noopener(bots):
    html = render_footer()
    for href in _links(html):
        if href.startswith("http"):
            block = re.search(rf'<a[^>]*href="{re.escape(href)}"[^>]*>', html).group(0)
            assert 'rel="noopener"' in block and 'target="_blank"' in block


async def test_support_block_is_on_every_page(client):
    for path in ("/", "/salons", "/tariffs", "/about"):
        r = await client.get(path)
        assert "footer-support" in r.text, path
        assert "Есть вопрос?" in r.text, path


# ── боты понимают метку из ссылки ──────────────────────────────────────────

def test_both_bots_handle_the_support_payload():
    """Без обработчика Telegram отвечает «ссылка устарела» на исправную
    ссылку из подвала — проверка обязана стоять до разбора токена."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]

    tg = (root / "app" / "tg_bot.py").read_text(encoding="utf-8")
    assert 'SUPPORT_DEEP_LINK = "support"' in tg
    assert tg.index("if token == SUPPORT_DEEP_LINK") < tg.index("record = await r.hgetall(_key(token))")

    mx = (root / "app" / "max_bot.py").read_text(encoding="utf-8")
    assert 'SUPPORT_DEEP_LINK = "support"' in mx
    assert mx.index("if token == SUPPORT_DEEP_LINK") < mx.index("record = await r.hgetall(_key(token))")


def test_footer_link_payload_matches_the_bots():
    """Метка в ссылке и метка в ботах не должны разъехаться."""
    from app.tg_bot import SUPPORT_DEEP_LINK as tg_mark
    from app.max_bot import SUPPORT_DEEP_LINK as max_mark
    assert tg_mark == max_mark == "support"


def _vk_href(monkeypatch, audience, *, clients=True):
    monkeypatch.setattr(settings, "VK_GROUP_ID", 1001)
    monkeypatch.setattr(settings, "VK_GROUP_SCREEN_NAME", "rumi_biz")
    monkeypatch.setattr(settings, "VK_CLIENTS_GROUP_ID", 2002 if clients else 0)
    monkeypatch.setattr(settings, "VK_CLIENTS_GROUP_SCREEN_NAME", "rumi_clients")
    return [h for h in _links(render_footer(None, audience)) if "vk.me" in h]


def test_vk_link_goes_to_client_community_on_ordinary_pages(monkeypatch):
    assert _vk_href(monkeypatch, "client") == ["https://vk.me/rumi_clients?ref=support"]
    assert [h for h in _links(render_footer()) if "vk.me" in h] == ["https://vk.me/rumi_clients?ref=support"]


def test_vk_link_goes_to_business_community_on_business_pages(monkeypatch):
    assert _vk_href(monkeypatch, "business") == ["https://vk.me/rumi_biz?ref=support"]


def test_vk_link_falls_back_to_business_without_client_community(monkeypatch):
    assert _vk_href(monkeypatch, "client", clients=False) == ["https://vk.me/rumi_biz?ref=support"]


@pytest.mark.parametrize("path, expected", [
    ("/business", "rumi_biz"), ("/salons", "rumi_clients"), ("/", "rumi_clients"),
    ("/tariffs", "rumi_biz"),
])
async def test_real_pages_pick_the_right_community(client, monkeypatch, path, expected):
    _vk_href(monkeypatch, "client")
    r = await client.get(path)
    assert r.status_code == 200
    assert f"https://vk.me/{expected}?ref=support" in r.text
