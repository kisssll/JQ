"""Три экрана по макетам дизайнера: главная, каталог, карточка салона.

Решение 0014, заход 2. Здесь проверяется то, что при пересборке композиции
легко потерять: наши данные и ограничения (карточка без фото, свободные окна,
соло-режим, запись на телефоне) и то, что макет принёс (арка, бренд-строка,
порядок блоков). Окна и цену запросов считают соседние тесты
(test_catalog_cards.py) — здесь не дублируем, а проверяем форму.
"""
import re
from pathlib import Path

from app.services.catalog_slots import SLOTS_PER_CARD
from app.web.components import ui
from app.web.components.tbank import render_tbank_partner_banner
from app.models.models import SalonPanelMode
from tests.test_catalog_cards import _card, _stand

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "static" / "src" / "css"


def _block(css: str, selector: str) -> str:
    """Тело первого правила с точным селектором."""
    start = css.index(selector + " {")
    return css[start:css.index("}", start)]


# ─────────────────────────── главная ───────────────────────────

async def test_home_has_the_brand_line_and_the_merged_copy(client):
    html = (await client.get("/")).text
    # Строка бренда — одна, как у дизайнера и Дианы: «руми. Твой доступ к красоте».
    assert "руми. Твой доступ <em>к красоте</em>" in html
    assert "РУМИ. Твой доступ" not in html
    assert "Мастера и салоны в одном приложении" in html
    assert "Подберём салон и услуги для вас" in html
    assert "Управлять салоном с нами <em>проще</em>" in html
    assert "Для прекрасных и смелых, как ты!" in html
    # Опечатка Дианы «агенство» не должна вернуться.
    assert "агенство" not in html
    assert "не через агентство" in html


async def test_home_promises_are_ones_the_code_can_keep(client):
    """«В один клик» и «за 15 минут» код не гарантирует — их быть не должно.
    «До 100%» — решение владельца (0011, п. 15): остаётся, но один раз и не
    крупной цифрой, как в макете («не усиливай»)."""
    html = (await client.get("/")).text
    # Подвал общий для всех страниц и его тексты — не этого захода; проверяем
    # то, что собрано на самой главной.
    html = html.split("<footer")[0]
    assert "в один клик" not in html
    assert "за 15 минут" not in html
    assert "30 секунд" not in html
    assert html.count("до 100%") == 1
    assert "big-stat" not in html
    assert not re.search(r"до\s*70\s*%", html)


async def test_home_hero_uses_the_arch_and_keeps_search_first(client):
    html = (await client.get("/")).text
    hero = html[html.index('class="home-hero"'):html.index('class="home-catalog"')]
    assert 'home-hero__art r-arch' in hero
    # Поиск стоит в тексте до арки: на телефоне арки нет, поиск первый.
    assert hero.index('role="search"') < hero.index("home-hero__art")
    # Градиентной заглушки вместо снимка в арке нет (docs/design.md).
    assert "gradient" not in hero


def test_home_hero_photos_exist_and_load_only_on_wide_screens():
    """Оба снимка арки живут в CSS и ТОЛЬКО внутри медиазапроса.

    На телефоне арка скрыта (`display: none`), но это не отменяет загрузку:
    объявленный вне медиазапроса фон браузер всё равно скачает, и телефон
    заплатит полторы сотни килобайт за картинку, которой на экране нет.
    """
    css = (ROOT / "static" / "src" / "css" / "home.css").read_text()
    for name in ("home-hero-light.webp", "home-hero-dark.webp"):
        assert (ROOT / "static" / "images" / name).exists(), f"нет файла {name}"
        at = css.find(name)
        assert at > 0, f"{name} не подключён в home.css"
        # Правило внутри медиазапроса лежит на втором уровне скобок: @media { .x { … } }.
        before = css[:at]
        assert before.count("{") - before.count("}") >= 2, (
            f"{name} объявлен вне медиазапроса — телефон скачает его зря")


def test_dark_theme_gets_its_own_hero_photo():
    """Тёмный снимок включает :root[data-theme="dark"].

    Голый [data-theme="dark"] брать нельзя: тот же атрибут стоит на кнопке
    выбора темы в профиле (объяснение в design-tokens.css). И не
    prefers-color-scheme: системную схему наши стили не слушают, тема живёт
    атрибутом, иначе снимок разойдётся с палитрой страницы.
    """
    css = (ROOT / "static" / "src" / "css" / "home.css").read_text()
    at = css.find("home-hero-dark.webp")
    rule = css.rfind("{", 0, at)
    head = css[css.rfind("}", 0, rule) + 1:rule]
    selector = re.sub(r"/\*.*?\*/", "", head, flags=re.S).strip()
    assert selector.startswith(':root[data-theme="dark"]'), selector
    assert ".home-hero__art" in selector, selector


async def test_home_partner_block_is_untouched(client):
    """Договор и маркировка: компонент отдаёт разметку, главная её не правит."""
    html = (await client.get("/")).text
    assert render_tbank_partner_banner() in html


async def test_home_blocks_all_stand_with_a_few_salons(client, db_session):
    """Два салона — две карточки и все остальные блоки на месте, без пустой
    сетки на тридцать мест."""
    for i in range(2):
        await _stand(db_session, f"МалоСалоновZZ{i}")
    html = (await client.get("/")).text
    assert html.count('class="r-salon salon-card"') == 2
    assert "Смотреть все салоны" in html
    assert len(re.findall(r'class="home-step"', html)) == 4
    assert len(re.findall(r'class="home-tile"', html)) == 4
    assert 'id="become-model"' in html and 'id="for-business"' in html


async def test_home_blocks_all_stand_with_no_salons(client):
    html = (await client.get("/")).text
    assert "Здесь появятся мастера и салоны" in html
    assert len(re.findall(r'class="home-step"', html)) == 4
    assert 'id="for-business"' in html


# ─────────────────────────── каталог ───────────────────────────

def test_card_marks_stand_above_the_name():
    """Метки («Победитель конкурса», «Продвигается») — над именем, как теги в
    макете: сначала почему карточка наверху, потом кто это. Метки видны всегда,
    иначе подъём оплаченных карточек был бы скрытой рекламой."""
    html = ui.salon_card(
        salon_id=1, name="ИмяZZ", href="/salons/1", city="Томск",
        badges=(ui.status("Победитель конкурса Руми", "accent"),
                ui.status("Продвигается", "neutral")),
    )
    assert html.index("r-salon__tags") < html.index("r-salon__top")
    assert "Победитель конкурса Руми" in html and "Продвигается" in html


def test_card_without_marks_has_no_empty_tags_row():
    html = ui.salon_card(salon_id=1, name="ИмяZZ", href="/salons/1")
    assert "r-salon__tags" not in html
    assert "Услуги пока не выложены" in html


async def test_catalog_card_keeps_services_and_slots_in_the_new_shape(client, db_session):
    """Макет не знает про свободные окна, у нас они сильнее снимка: после
    пересборки они на месте, а действие карточки — кнопка-капсула."""
    salon_id, _ = await _stand(db_session, "ОкнаЕщёЕстьZZ",
                               services=(("Стрижка", 2000, 45),))
    card = _card((await client.get("/salons")).text, salon_id)
    assert "Стрижка" in card and "2 000 ₽" in card and "45 мин" in card
    assert "Ближайшее время" in card
    assert 1 <= card.count('class="r-slot"') <= SLOTS_PER_CARD
    assert 'class="r-salon__all"' in card


def test_card_action_is_a_capsule_with_a_44px_target():
    block = _block((CSS / "ui.css").read_text(), ".r-salon__all")
    assert "min-height: var(--control-h)" in block
    assert "border-radius: var(--radius-pill)" in block


def test_catalog_title_and_search_share_a_row_on_wide_screens_only():
    css = (CSS / "salons.css").read_text()
    wide = css[css.index("@media (min-width: 900px) {\n    .catalog-hero"):]
    wide = wide[:wide.index("\n}\n") + 3]
    assert "grid-template-columns: minmax(0, 1fr) minmax(0, 30rem)" in wide
    # Базовое правило — одна колонка: на 375px поиск идёт под заголовком.
    base = _block(css, ".catalog-hero .section-container")
    assert "grid-template-columns: minmax(0, 1fr);" in base


async def test_catalog_filters_and_sorting_are_still_rendered(client):
    html = (await client.get("/salons")).text
    for needle in ('id="salonsFilterForm"', 'id="searchInput"', 'id="salons-list"',
                   "window.salonFilters"):
        assert needle in html, needle


# ─────────────────────── карточка салона ───────────────────────

async def test_salon_page_without_photo_and_description_is_complete(client, db_session):
    salon_id, _ = await _stand(db_session, "БезФотоСтраницаZZ")
    r = await client.get(f"/salons/{salon_id}")
    assert r.status_code == 200
    page = r.text
    assert "БезФотоСтраницаZZ" in page
    assert "Томск" in page
    # Нет описания и фото — нет и пустых блоков под них.
    assert "salon-about" not in page
    assert "salon-photos" not in page
    # Монограмма вместо снимка, в арке (форма — в CSS).
    assert 'class="r-mark r-mark--xl"' in page


async def test_booking_is_reachable_on_a_narrow_screen(client, db_session):
    """Колонка записи на телефоне скрыта, поэтому закреплённая кнопка и лист
    снизу обязаны быть в разметке — иначе записаться нельзя."""
    salon_id, _ = await _stand(db_session, "ЗаписьУзкийZZ")
    page = (await client.get(f"/salons/{salon_id}")).text
    assert 'id="bookDock"' in page
    assert 'data-sheet-open="bookSheet"' in page
    assert 'id="bookSheet"' in page
    css = (CSS / "salon-detail.css").read_text()
    assert "display: none" in _block(css, ".salon-aside")      # на телефоне колонки нет
    assert "position: sticky" in css                           # на широком — липкая


async def test_solo_page_speaks_about_a_person_and_team_page_about_a_salon(client, db_session):
    solo_id, _ = await _stand(db_session, "СоловойZZ", mode=SalonPanelMode.SOLO)
    team_id, _ = await _stand(db_session, "КомандаZZ", mode=SalonPanelMode.TEAM, masters=2)
    solo = (await client.get(f"/salons/{solo_id}")).text
    team = (await client.get(f"/salons/{team_id}")).text
    assert "Мастер · Томск" in solo
    assert 'id="team"' not in solo
    assert "Салон · Томск" in team
    assert 'id="team"' in team


# ─────────────────────────── арка ───────────────────────────

def test_arch_is_a_technique_used_in_two_places_not_everywhere():
    """Арка — для крупных иллюстративных блоков. Если её начнут вешать на
    карточки, приём перестанет быть приёмом."""
    users = []
    for p in CSS.rglob("*.css"):
        if p.name == "design-tokens.css":
            continue
        n = p.read_text().count("var(--radius-arch)")
        if n:
            users.append((p.name, n))
    assert sorted(users) == [("salon-detail.css", 1), ("ui.css", 1)], users
    pages = [p.name for p in (ROOT / "app" / "web").rglob("*.py")
             if "r-arch" in p.read_text()]
    assert pages == ["home.py"], pages


# ─────────────────────────── узкий экран ───────────────────────────

def test_search_buttons_are_44px_targets():
    """Кнопка «Найти» внутри капсулы поиска была 36px (малая кнопка) — палец
    промахивался. Цель не меньше 44px — правило проекта для 375px."""
    for name, sel in (("home.css", ".home-search .r-btn"),
                      ("salons.css", ".catalog-search .r-btn")):
        block = _block((CSS / name).read_text(), sel)
        assert "min-height: var(--control-h)" in block, name


def test_salon_name_gets_its_own_line_on_phones():
    """В строке с монограммой и сердечком имя получало ~180px и рвалось по
    слогам («ВИТРИ-НА-команда»). На телефоне имя уходит на свою строку."""
    css = (CSS / "salon-detail.css").read_text()
    narrow = css[css.index("@media (max-width: 639px) {\n    .salon-head"):]
    narrow = narrow[:narrow.index("\n}\n")]
    assert "flex-wrap: wrap" in narrow
    assert ".salon-head__id { order: 3; flex-basis: 100%; }" in narrow
    # а правило стоит ПОСЛЕ базового .salon-head__id — иначе оно проигрывает
    assert css.index(".salon-head__id {") < css.index("@media (max-width: 639px) {\n    .salon-head")
