# tests/test_seo_markup.py
"""Разметка для поисковых систем: карта сайта и Schema.org.

По запросу «руми» поисковику неоткуда узнать, что «Руми», «Rumi» и ООО «РУМИ»
— одно и то же: слово в выдаче занято персидским поэтом, а домен с двойной «r»
точного совпадения не даёт. Разметка заявляет бренд явно.
"""
import json
import re

import pytest

from app.web.components.structured_data import render_site_schema
from app.web.pages.legal import DOCUMENTS


def _schema(html: str) -> dict:
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    assert m, "блока JSON-LD на странице нет"
    return json.loads(m.group(1).replace("<\\/", "</"))


def test_schema_is_valid_json_and_names_the_brand():
    graph = _schema(render_site_schema())["@graph"]
    org = [n for n in graph if n["@type"] == "Organization"][0]
    assert org["name"] == "Руми"
    for alias in ("Rumi", "РУМИ", "rrumi"):
        assert alias in org["alternateName"], alias


def test_schema_ties_the_brand_to_the_legal_entity():
    """ИНН/ОГРН — сильный сигнал для Яндекса: он связывает сайт с реальной
    организацией. Реквизиты те же, что в подвале и документах."""
    org = [n for n in _schema(render_site_schema())["@graph"]
           if n["@type"] == "Organization"][0]
    assert org["taxID"] == "7000036144"
    assert org["vatID"] == "1267000004370"
    assert org["address"]["addressLocality"] == "Томск"


def test_schema_search_action_points_at_a_real_parameter():
    """Цель SearchAction должна вести на живой поиск, иначе подсказка в
    выдаче ведёт в никуда."""
    site = [n for n in _schema(render_site_schema())["@graph"]
            if n["@type"] == "WebSite"][0]
    target = site["potentialAction"]["target"]["urlTemplate"]
    assert target.startswith("https://rrumi.ru/salons?q=")


def test_schema_escapes_closing_tags():
    """Строка «</» внутри JSON закрыла бы <script> раньше времени."""
    assert "</" not in render_site_schema()[:-len("</script>")]


async def test_home_page_carries_the_schema_and_canonical(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert _schema(r.text)["@graph"]
    assert '<link rel="canonical" href="https://rrumi.ru/">' in r.text
    assert "Руми" in re.search(r'<meta name="description" content="(.*?)"', r.text).group(1)


async def test_schema_only_on_the_home_page(client):
    """Организацию робот берёт с корня один раз — копии на каждой странице
    только раздувают HTML."""
    for path in ("/salons", "/tariffs", "/about"):
        assert "application/ld+json" not in (await client.get(path)).text, path


# ── карта сайта ────────────────────────────────────────────────────────────

async def _sitemap(client) -> str:
    r = await client.get("/sitemap.xml")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    return r.text


@pytest.mark.parametrize("path", ["/", "/salons", "/evening-deals", "/business",
                                  "/model", "/tariffs", "/about", "/legal"])
async def test_sitemap_lists_the_public_pages(client, path):
    body = await _sitemap(client)
    assert f"<loc>https://rrumi.ru{path}</loc>" in body.replace("rrumi.ru//", "rrumi.ru/"), path


async def test_sitemap_lists_the_legal_documents(client):
    """Документы ищут по названию — они должны находиться."""
    body = await _sitemap(client)
    for slug in DOCUMENTS:
        assert f"<loc>https://rrumi.ru/{slug}</loc>" in body, slug


async def test_sitemap_drops_the_auth_forms(client):
    """Индексировать в форме входа нечего, а карту она разбавляет."""
    body = await _sitemap(client)
    assert "/login</loc>" not in body
    assert "/register</loc>" not in body


async def test_sitemap_entries_carry_priority(client):
    body = await _sitemap(client)
    assert "<priority>1.0</priority>" in body      # главная
    assert body.count("<priority>") == body.count("<url>")
