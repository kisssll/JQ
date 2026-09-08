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
