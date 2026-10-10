"""«Вечерние окна» и «Правила конкурса» в клиентском мире (решение 0011).

Проверяется то, что при переделке вида легко потерять: условия конкурса на
странице должны идти из кода, а не из переписанного текста; карточка
предложения не должна держаться на фотографии; пустое состояние обязано
вести в каталог; страницы не заводят вторую кнопку и вторую карточку.
"""
import re
from datetime import date

from app.services import contest
from app.web.pages import contest as contest_page
from tests.test_evening_deals import _mk_salon_deal


def _main(html: str) -> str:
    return html[html.index("<main"):html.index("</main>")]


# ── конкурс ─────────────────────────────────────────────────────────────────

async def test_contest_page_shows_terms_from_code(client):
    r = await client.get("/contest")
    assert r.status_code == 200
    text = r.text
    for day in (contest.ENTRY_START, contest.ENTRY_END, contest.VOTING_START,
                contest.VOTING_END, contest.RESULTS_DATE, contest.FINAL_DATE):
        assert contest.ru_date(day) in text, day
    for value in (contest.PRIZE, contest.CONTACT_EMAIL, contest.HASHTAG,
                  contest.VK_GROUP_URL, f"от {contest.MIN_AGE} лет",
                  f"({contest.WINNERS} человека)"):
        assert value in text, value
    # «ООО «РУМИ»» экранируется кавычками-ёлочками без изменений, а вот
    # организатор целиком идёт одной строкой из кода.
    assert contest.ORGANIZER in text


async def test_contest_page_follows_the_code_not_a_copy(client, monkeypatch):
    """Подмена значений в contest.py обязана сразу попасть на страницу: если
    сроки переписаны на странице руками, подмена их не заденет."""
    monkeypatch.setattr(contest, "FINAL_DATE", date(2026, 11, 5))
    monkeypatch.setattr(contest, "PRIZE", "сертификат на ЧУЖОЙ_ПРИЗ")
    monkeypatch.setattr(contest, "ORGANIZER", "ООО «ЧУЖОЙ_ОРГАНИЗАТОР»")
    r = await client.get("/contest")
    assert "5 ноября" in r.text
    assert "ЧУЖОЙ_ПРИЗ" in r.text
    assert "ЧУЖОЙ_ОРГАНИЗАТОР" in r.text
    assert "31 октября" not in r.text


async def test_contest_page_uses_shared_components(client, monkeypatch):
    # Патчим settings ТАМ, где страница его читает: другие тесты подменяют
    # настройки в процессе, и объект из app.core.config к этому моменту другой.
    monkeypatch.setattr(contest_page.settings, "TG_BOT_USERNAME", "rumi_test_bot")
    r = await client.get("/contest")
    body = _main(r.text)
    assert "r-display" in body and "r-facts" in body
    assert "r-btn--primary" in body
    assert 'rel="noopener"' in body
    # Своей разметки кнопок, инлайновых стилей и старых классов быть не должно.
    for old in ("btn-outline", "btn-primary", "text-display", "text-heading", 'style="'):
        assert old not in body, old


# ── вечерние окна ───────────────────────────────────────────────────────────

async def test_evening_offer_renders_without_photo(client, db_session):
    ctx = await _mk_salon_deal(db_session, name="БезФотоQQ", owner_phone="+79995554071")
    r = await client.get("/evening-deals")
    assert r.status_code == 200
    card = re.search(r'<article class="r-salon r-deal".*?</article>', r.text, re.S)
    assert card, "карточка предложения не отрисована"
    html = card.group(0)
    assert "БезФотоQQ" in html
    # Вместо снимка — монограмма: первая буква названия, а не пустое место.
    assert 'class="r-mark r-mark--lg"' in html and ">Б</span>" in html
    assert "<img" not in html
    # Кто, что, когда, почём: мастер, услуга, окно, цена до и после скидки.
    assert "Мастер" in html and "Стрижка" in html
    assert "13:00" in html
    assert "1 000 ₽" in html and "800 ₽" in html
    assert "Скидка −20%" in html
    assert f'href="/salons/{ctx["salon_id"]}"' in html


async def test_evening_empty_state_leads_to_catalog(client):
    r = await client.get("/evening-deals", params={"city": "НетТакогоГородаXX"})
    assert r.status_code == 200
    # Ссылка проверяется внутри самого пустого состояния: в подвале страницы
    # «/salons» есть всегда, и проверка по всей странице проходила бы вхолостую.
    empty = re.search(r'<div class="r-empty".*?</a>', _main(r.text), re.S)
    assert empty, "нет пустого состояния"
    assert 'href="/salons"' in empty.group(0)


async def test_evening_page_uses_shared_components(client, db_session):
    await _mk_salon_deal(db_session, name="ОбщиеКомпонентыQQ", owner_phone="+79995554072")
    r = await client.get("/evening-deals")
    body = _main(r.text)
    for shared in ("r-display", "r-salon-grid", "r-svc__row", "r-slot", "r-btn--primary"):
        assert shared in body, shared
    for old in ("evening-card", "evening-badge", "evening-slot", "btn-primary",
                "text-display", "<style"):
        assert old not in body, old
