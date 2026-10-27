# tests/test_header_account_cabinet.py
"""Шапка, этикетка-вход и оболочка кабинета (решение 0015, п. 1–4)."""
import re
from types import SimpleNamespace

from sqlalchemy import update

from app.models.models import User, UserRole
from app.web.components.header import PUBLIC_NAV, render_account_tag, render_header
from tests.conftest import register_user

PUBLIC_HREFS = ["/", "/salons", "/business", "/model", "/about", "/tariffs"]


def _nav_hrefs(html: str) -> list[str]:
    nav = html.split('id="header-nav"', 1)[1].split("</nav>", 1)[0]
    return re.findall(r'class="header-link[^"]*" href="([^"]+)"', nav)


def _menu(html: str) -> str:
    return html.split('id="acct-menu"', 1)[1].split("</nav>", 1)[0]


def _guest_user(**kw):
    base = dict(full_name="Анна Ветрова", phone="+79990000001", role=UserRole.CLIENT,
                is_model=False, has_salon_access=False, has_master_profile=False)
    base.update(kw)
    return SimpleNamespace(**base)


def test_header_has_exactly_six_public_links_in_order():
    html = render_header("home")
    assert _nav_hrefs(html) == PUBLIC_HREFS
    assert [h for _, h, _ in PUBLIC_NAV] == PUBLIC_HREFS


def test_active_item_is_marked_and_only_one():
    html = render_header("salons")
    assert html.count('aria-current="page"') == 1
    assert 'class="header-link active" href="/salons" aria-current="page"' in html


async def test_public_pages_render_the_same_header(client):
    for path in ("/", "/salons", "/business", "/model", "/about", "/tariffs"):
        r = await client.get(path)
        assert r.status_code == 200, path
        assert _nav_hrefs(r.text) == PUBLIC_HREFS, path
        assert "sidebar" not in r.text, path


def test_tag_gives_a_guest_login_and_registration_only():
    menu = _menu(render_account_tag(None))
    assert 'href="/login"' in menu and 'href="/register"' in menu
    for private in ("/profile", "/bookings", "/favorites", "/logout", "/admin"):
        assert private not in menu


def test_tag_gives_a_member_his_links_and_logout():
    menu = _menu(render_account_tag(_guest_user()))
    for href in ("/profile", "/bookings", "/favorites", "/logout"):
        assert f'href="{href}"' in menu
    assert "/login" not in menu
    # панели и админки у обычного клиента нет
    assert "/business/dashboard" not in menu and "/admin" not in menu


def test_tag_shows_panel_and_admin_only_to_those_who_have_them():
    menu = _menu(render_account_tag(_guest_user(has_salon_access=True)))
    assert 'href="/business/dashboard"' in menu
    menu = _menu(render_account_tag(_guest_user(has_master_profile=True)))
    assert 'href="/business/dashboard"' in menu
    menu = _menu(render_account_tag(_guest_user(is_model=True)))
    assert 'href="/model/dashboard"' in menu
    menu = _menu(render_account_tag(_guest_user(role=UserRole.ADMIN)))
    assert 'href="/admin"' in menu


def test_tag_is_a_real_button_and_makes_no_promises():
    html = render_account_tag(None)
    assert re.search(r'<button type="button" class="acct-tag__btn"[^>]*aria-expanded="false"',
                     html, re.S)
    assert "hidden" in html.split('id="acct-menu"', 1)[1].split(">", 1)[0]
    assert "30 секунд" not in html and "4 клика" not in html and "0 звонков" not in html


def test_tag_survives_a_blank_name():
    """Имя из одних пробелов проходит форму профиля (full_name пишется как есть),
    а на нём этикетка валила 500 КАЖДУЮ страницу с шапкой, не только профиль."""
    html = render_account_tag(_guest_user(full_name="   "))
    assert "+79990000001" in html
    # телефона тоже может не быть — тогда остаётся подпись по умолчанию
    html = render_account_tag(_guest_user(full_name=" ", phone=""))
    assert "Пользователь" in html


def test_tag_escapes_the_name():
    html = render_account_tag(_guest_user(full_name='<img src=x onerror=alert(1)>'))
    assert "<img src=x" not in html


def test_panel_header_has_no_tag():
    html = render_header("business", _guest_user(), panel=True)
    assert "acct-tag" not in html and 'id="header-nav"' not in html
    assert 'href="/logout"' in html


async def test_business_panel_has_no_tag(client):
    data = await register_user(client, "+79997771101")
    client.cookies.set("access_token", data["access_token"])
    r = await client.post("/api/v1/business/apply", data={
        "salon_name": "Шапка", "phone": "+79997771101", "offer_accepted": "1",
        "pd_consent": "1", "plan": "lite", "for_master": "1",
    })
    salon_id = r.json()["salon_id"]
    r = await client.get(f"/business/dashboard?salon_id={salon_id}")
    assert r.status_code == 200
    assert "acct-tag" not in r.text and "sidebar" not in r.text
    # а на обычной странице у того же человека этикетка есть и ведёт в панель
    r = await client.get("/")
    assert 'href="/business/dashboard"' in _menu(r.text)


async def test_business_landing_has_master_button(client):
    r = await client.get("/business")
    assert r.status_code == 200
    assert re.search(r'<a href="/dlya-masterov"[^>]*>\s*Начать как мастер', r.text)
    # «Подключить салон» никуда не делась
    assert 'href="/business/checkout?plan=business"' in r.text


async def test_three_cabinet_pages_share_the_side_column(client, db_session):
    data = await register_user(client, "+79997771102")
    client.cookies.set("access_token", data["access_token"])
    columns = []
    for path in ("/profile", "/bookings", "/favorites"):
        r = await client.get(path)
        assert r.status_code == 200, path
        side = r.text.split('<aside class="acc-side"', 1)[1].split("</aside>", 1)[0]
        links = re.findall(r'href="([^"]+)" class="acc-link( on)?"', side)
        assert [h for h, _ in links] == ["/profile", "/bookings", "/favorites"], path
        assert [h for h, on in links if on] == [path], path   # подсвечен свой раздел
        assert 'href="/logout"' in side
        assert "Портфолио" not in side
        same = side.replace(' aria-current="page"', "").replace("acc-link on", "acc-link")
        columns.append(same)
    assert columns[0] == columns[1] == columns[2]


async def test_cabinet_shows_no_invented_numbers(client):
    """У нового человека нет ни записей, ни избранного: числовых плиток нет."""
    data = await register_user(client, "+79997771103")
    client.cookies.set("access_token", data["access_token"])
    for path in ("/bookings", "/favorites"):
        r = await client.get(path)
        assert 'class="acc-stats"' not in r.text, path
    assert "acc-badge" not in (await client.get("/profile")).text


def test_cabinet_numbers_are_in_russian():
    """«1 салонов» и «1 предстоящих» — ровно то, что видел клиент с одной
    записью: подписи в макете статичны, а число под ними меняется."""
    from app.web.components.cabinet import plural

    salon = lambda n: plural(n, "салон", "салона", "салонов")
    assert [salon(n) for n in (1, 2, 5, 11, 21, 104)] == [
        "салон", "салона", "салонов", "салонов", "салон", "салона"
    ]
