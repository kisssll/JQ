# tests/test_about_tariffs_pages.py
"""«Манифест» и «Тарифы и информация» по макету дизайнера (решение 0016, п. 2)."""
import re

from app.services.tariffs import MODEL_TARIFF_CATALOG, TARIFF_CATALOG
from app.web.components.header import PUBLIC_NAV
from app.web.pages.legal import DOCUMENTS
from app.web.pages.tariffs import _SITE_INSTRUCTIONS
from tests.test_design_tokens import _theme_blocks, contrast

PUBLIC_HREFS = [h for _, h, _ in PUBLIC_NAV]


def _nav_hrefs(html: str) -> list[str]:
    nav = html.split('id="header-nav"', 1)[1].split("</nav>", 1)[0]
    return re.findall(r'href="([^"]+)"', nav)


def _money(v) -> str:
    return f"{int(v):,}".replace(",", " ")


async def test_both_pages_are_200_with_the_six_item_header(client):
    for path in ("/about", "/tariffs"):
        r = await client.get(path)
        assert r.status_code == 200, path
        assert _nav_hrefs(r.text) == PUBLIC_HREFS, path


async def test_manifest_has_dark_hero_columns_removed_list_and_quote(client):
    html = (await client.get("/about")).text
    assert 'class="about-hero"' in html
    assert "Манифест" in html and "<em>вы и мастер</em>" in html
    assert 'class="about-drop"' in html
    assert html.count("<li>") >= 6
    assert re.search(r'<ul class="about-removed">(?:<li>[^<]+</li>){6}</ul>', html)
    assert "Звонки в салон" in html and "Регистрации, которые ни на что не влияют" in html
    assert 'class="about-quote"' in html
    assert 'href="/salons"' in html and "Найти салон" in html
    # партнёрство с Т-Банком осталось и несёт маркировку рекламы
    assert "Мы стали партнёрами Т-Банка" in html and "tb-products" in html


async def test_manifest_has_no_stub_illustration_and_no_third_arch(client):
    html = (await client.get("/about")).text
    assert "r-arch" not in html
    assert "<img" not in html.split('class="about-body"', 1)[1].split("news-tbank", 1)[0]


async def test_tariff_prices_come_from_the_catalog(client):
    html = (await client.get("/tariffs")).text
    for name, t in TARIFF_CATALOG.items():
        price = t.unit_price if t.billing == "per_employee" else t.amount
        assert f'<span class="amount">{_money(price)} ₽</span>' in html, name
    for name, t in MODEL_TARIFF_CATALOG.items():
        assert f'<span class="amount">{_money(t.amount)} ₽</span>' in html, name
    amounts = re.findall(r'<span class="amount">([^<]+)</span>', html)
    expected = {f"{_money(t.unit_price if t.billing == 'per_employee' else t.amount)} ₽"
                for t in TARIFF_CATALOG.values()}
    expected |= {f"{_money(t.amount)} ₽" for t in MODEL_TARIFF_CATALOG.values()}
    expected |= {"По запросу"}
    assert set(amounts) <= expected, set(amounts) - expected


async def test_three_tabs_render_one_pane_active_each(client):
    for key, pane in (("", "plans"), ("plans", "plans"), ("documents", "documents"),
                      ("guides", "guides"), ("мусор", "plans")):
        r = await client.get("/tariffs" + (f"?tab={key}" if key else ""))
        assert r.status_code == 200
        html = r.text
        active = re.findall(r'id="tab-(\w+)" class="tab-content active"', html)
        assert active == [pane], (key, active)
        assert html.count('aria-selected="true"') == 1
    html = (await client.get("/tariffs")).text
    assert [m for m in re.findall(r'class="tariffs-tab[^"]*" role="tab"', html)] and \
        html.count('role="tab"') == 3


async def test_every_document_link_answers_200_and_has_its_date(client):
    html = (await client.get("/tariffs?tab=documents")).text
    hrefs = re.findall(r'class="doc-card" href="([^"]+)"', html)
    assert hrefs == [f"/{d['slug']}" for d in DOCUMENTS.values()]
    assert len(hrefs) == 6
    for h in hrefs:
        assert (await client.get(h)).status_code == 200, h
    assert html.count("Редакция от ") == 6
    assert "5 сентября 2026" in html          # у cookie своя дата
    assert html.count("18 августа 2026") == 5


async def test_no_moderation_deadline_is_promised(client):
    """Срока модерации в коде нет — решение принимает человек. Обещание срока —
    ч. 7 ст. 5 закона «О рекламе»."""
    for path in ("/tariffs?tab=guides", "/tariffs", "/about"):
        html = (await client.get(path)).text
        assert not re.search(r"1\s*[–-]\s*2\s+рабоч", html), path
    assert "рабочих дн" not in " ".join(t for _, t in _SITE_INSTRUCTIONS)


def test_hero_captions_are_readable_on_dark_in_both_themes():
    """Тёмный первый экран манифеста: подписи по минимумам из docs/design.md."""
    light, dark = _theme_blocks()
    for name, pal in (("light", light), ("dark", dark)):
        for fg in ("--color-on-dark", "--color-rose-strong"):
            ratio = contrast(pal[fg], pal["--color-dark"])
            assert ratio >= 4.5, f"{name}: {fg} на dark = {ratio:.2f}"
