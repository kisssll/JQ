from types import SimpleNamespace

from app.web.pages.sport_tariffs import render_sport_tariffs_page


def test_sport_tariffs_page_uses_sport_navigation_and_shows_club_plans():
    plan = SimpleNamespace(
        name="Абонемент",
        price=12500,
        unit="месяц",
        items=["Безлимитные тренировки"],
    )
    organization = SimpleNamespace(
        name="Спарта",
        city="Томск",
        slug="sparta",
    )

    page = render_sport_tariffs_page(plans=[(plan, organization)])
    nav = page.split('id="header-nav"', 1)[1].split("</nav>", 1)[0]

    assert 'href="/sport/tariffs"' in nav
    assert 'href="/business"' not in nav
    assert "Стать моделью" not in nav
    assert "Спарта" in page
    assert "12 500 ₽" in page
    assert "/sport/sparta/prices" in page


def test_sport_tariffs_page_shows_empty_state_when_no_club_plans():
    page = render_sport_tariffs_page()

    assert "Пока нет опубликованных тарифов" in page
    assert 'href="/sport/"' in page
