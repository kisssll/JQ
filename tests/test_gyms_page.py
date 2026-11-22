import asyncio
from types import SimpleNamespace

from app.web.pages.gyms import (
    GymQuery,
    _render_card,
    render_gyms_grid,
    render_gyms_page,
)


def test_gym_card_escapes_content_and_links_to_its_page():
    gym = SimpleNamespace(
        id=17,
        name="<Sparta>",
        slug="sparta",
        city="Tomsk & area",
        description="Club <sport>",
        logo_url="",
    )

    card = _render_card(gym)

    assert 'class="r-salon gym-card"' in card
    assert 'href="/sport/sparta"' in card
    assert "&lt;Sparta&gt;" in card
    assert "Tomsk &amp; area" in card
    assert "Club &lt;sport&gt;" in card


def test_club_catalog_uses_its_own_route_for_navigation_and_empty_state():
    class EmptyResults:
        def scalars(self):
            return self

        def all(self):
            return []

    class EmptyDatabase:
        async def execute(self, *args, **kwargs):
            return EmptyResults()

    page = asyncio.run(
        render_gyms_page(
            EmptyDatabase(),
            query=GymQuery(),
            current_page="sport_clubs",
            catalog_path="/sport/clubs",
        )
    )
    nav = page.split('id="header-nav"', 1)[1].split("</nav>", 1)[0]

    assert 'href="/sport/clubs" aria-current="page"' in nav
    assert 'action="/sport/clubs"' in page
    assert 'href="/sport/clubs"' in page
    assert 'name="robots" content="noindex,follow"' not in page

    filtered_page = asyncio.run(
        render_gyms_page(
            EmptyDatabase(),
            query=GymQuery(q="boxing"),
            current_page="sport_clubs",
            catalog_path="/sport/clubs",
        )
    )
    assert 'name="robots" content="noindex,follow"' in filtered_page


def test_club_catalog_pagination_stays_on_its_route(monkeypatch):
    gyms = [
        SimpleNamespace(
            id=index,
            name=f"Club {index}",
            slug=f"club-{index}",
            city="Tomsk",
            description="",
            logo_url="",
        )
        for index in range(20)
    ]

    async def load_page(*args):
        return gyms, True

    monkeypatch.setattr("app.web.pages.gyms._load_page", load_page)
    grid = asyncio.run(
        render_gyms_grid(object(), GymQuery(q="boxing"), "/sport/clubs")
    )

    assert 'href="/sport/clubs?q=boxing&amp;limit=40"' in grid
