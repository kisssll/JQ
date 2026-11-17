from types import SimpleNamespace

from app.web.pages.gyms import _render_card


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
