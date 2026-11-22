from app.web.pages.sport_home import render_sport_home_page


def test_sport_home_promotes_catalog_and_club_application():
    page = render_sport_home_page()
    nav = page.split('id="header-nav"', 1)[1].split("</nav>", 1)[0]

    assert '<body class="sport-directory sport-home">' in page
    assert 'href="/sport/" aria-current="page"' in nav
    assert 'action="/sport/clubs"' in page
    assert 'href="/sport/clubs"' in page
    assert 'href="/sport/business"' in page
    assert 'href="/sport/tariffs"' in page
