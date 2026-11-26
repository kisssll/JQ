import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

from app.models.models import UserRole
from app.models.sport import SportOrganization
from app.web.components.footer import render_footer
from app.web.pages.login import render_login_page
from app.web.pages.legal import render_legal_page
from app.web.pages.password_reset import (
    render_forgot_password_page,
    render_reset_password_page,
)
from app.web.pages.register import render_register_page
from app.web.pages.sport_business import render_sport_business_dashboard_page
from app.web.pages.sport_business import render_sport_business_page
from app.web.pages.sport_home import render_sport_home_page
from app.web.pages.sport_tariffs import render_sport_tariffs_page
from app.web.components.header import render_account_tag, render_header
from app.web.views import render_status_page
from app.web.views import router as web_router
from app.services.auth_redirect import failure_page_url, safe_sport_redirect


def _request(path: str, query: str = "") -> Request:
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "query_string": query.encode(),
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    })


def test_sport_login_and_registration_keep_sport_context():
    login = render_login_page(_request("/login", "redirect=%2Fsport%2Fbusiness"))
    register = render_register_page(_request("/register", "redirect=%2Fsport%2Fbusiness"))

    assert '<body class="auth-page sport-directory rumi-sport">' in login
    assert '<body class="auth-page sport-directory rumi-sport">' in register
    assert '<p class="auth-context">Руми Спорт</p>' in login
    assert '<p class="auth-context">Руми Спорт</p>' in register
    assert 'href="/sport/forgot-password?redirect=%2Fsport%2Fbusiness"' in login
    assert 'value="/sport/business"' in register


def test_regular_login_does_not_get_sport_theme():
    page = render_login_page(_request("/login", "redirect=%2Fbusiness%2Fdashboard"))

    assert '<body class="auth-page">' in page
    assert '<p class="auth-context">Руми Спорт</p>' not in page


def test_sport_auth_routes_keep_shared_auth_forms_and_sport_return():
    login = render_login_page(_request("/sport/login"))
    register = render_register_page(_request("/sport/register"))

    assert '<body class="auth-page sport-directory rumi-sport">' in login
    assert '<body class="auth-page sport-directory rumi-sport">' in register
    assert 'name="redirect" value="/sport"' in login
    assert 'name="redirect" value="/sport"' in register
    assert 'name="auth_variant" value="sport"' in login
    assert 'name="auth_variant" value="sport"' in register
    assert 'action="/api/v1/auth/login-web"' in login
    assert 'action="/api/v1/auth/register-web"' in register
    assert "/sport/register?redirect=%2Fsport" in login
    assert "/sport/login?redirect=%2Fsport" in register
    assert 'href="/sport/forgot-password?redirect=%2Fsport"' in login
    assert 'name="redirect" value="/sport"' in render_login_page(
        _request("/sport/login", "redirect=%2Fbusiness")
    )
    assert 'name="redirect" value="/sport"' in render_register_page(
        _request("/sport/register", "redirect=%2Fbusiness")
    )
    assert safe_sport_redirect("/sport/../profile") == "/sport"


def test_sport_auth_routes_precede_the_organization_slug_route():
    paths = [route.path for route in web_router.routes]

    assert paths.index("/sport/login") < paths.index("/sport/{slug}")
    assert paths.index("/sport/register") < paths.index("/sport/{slug}")
    assert paths.index("/sport/logout") < paths.index("/sport/{slug}")
    assert paths.index("/sport/admin") < paths.index("/sport/{slug}")
    assert paths.index("/sport/forgot-password") < paths.index("/sport/{slug}")
    assert paths.index("/sport/reset-password") < paths.index("/sport/{slug}")
    assert paths.index("/sport/legal") < paths.index("/sport/{slug}")
    assert paths.index("/sport/legal/{slug}") < paths.index("/sport/{slug}")


def test_sport_header_links_to_sport_auth_routes():
    header = render_header("sport", None)
    beauty_header = render_header("home", None)

    assert 'href="/sport/login"' in header
    assert 'href="/sport/register"' in header
    assert 'src="/static/images/rumi-sport-logo.svg"' in header
    assert 'class="header-logo-sport"' in header
    assert 'alt="Руми Спорт"' in header
    assert 'src="/static/images/rumi-sport-logo.svg"' not in beauty_header


def test_sport_account_menu_stays_inside_sport():
    user = SimpleNamespace(
        full_name="Спорт Пользователь",
        phone="+79990000000",
        has_sport_access=False,
    )
    menu = render_account_tag(user, "sport")

    assert 'href="/sport/profile"' in menu
    assert 'href="/sport/bookings"' in menu
    assert 'href="/sport/favorites"' in menu
    assert 'href="/sport/clubs"' in menu
    assert 'href="/sport/logout"' in menu
    assert 'href="/logout"' not in menu
    assert 'href="/profile"' not in menu
    assert 'href="/sport/admin"' not in menu


def test_sport_account_menu_shows_admin_link_for_admin():
    admin_user = SimpleNamespace(
        full_name="Администратор",
        phone="+79991112233",
        has_sport_access=False,
        role=UserRole.ADMIN,
        has_role=lambda r: r == "admin",
    )
    menu = render_account_tag(admin_user, "sport")

    assert 'href="/sport/admin"' in menu
    assert 'href="/sport/profile"' in menu
    assert 'href="/sport/logout"' in menu


def test_sport_footer_and_documents_use_sport_routes():
    footer = render_footer(sport=True)
    document = render_legal_page("cookies", sport=True)

    assert 'href="/salons"' not in footer
    assert 'href="/business"' not in footer
    assert 'href="/terms"' not in footer
    assert 'href="/sport/legal/consent"' in footer
    assert 'href="/sport/legal/privacy"' in document
    assert 'href="/privacy"' not in document
    assert 'href="/sport/"' in document


def test_sport_public_pages_only_link_to_sport_internal_routes():
    pages = (
        render_sport_home_page(),
        render_sport_business_page(),
        render_sport_tariffs_page(),
    )
    internal_links = [
        href
        for page in pages
        for href in re.findall(r'<a\b[^>]*\bhref="([^"]+)"', page)
        if href.startswith("/")
    ]

    assert internal_links
    assert "/directions/beauty" in internal_links
    assert all(href in {"/sport", "/directions/beauty"} or href.startswith("/sport/") for href in internal_links)


def test_sport_password_recovery_stays_in_sport_flow():
    request = _request("/sport/forgot-password")
    forgot = render_forgot_password_page(request)
    reset = render_reset_password_page(_request("/sport/reset-password", "token=abc"))

    assert '<body class="auth-page sport-directory rumi-sport">' in forgot
    assert '<body class="auth-page sport-directory rumi-sport">' in reset
    assert 'name="auth_variant" value="sport"' in forgot
    assert 'name="auth_variant" value="sport"' in reset
    assert 'href="/sport/login?redirect=%2Fsport"' in forgot


def test_sport_oauth_error_returns_to_sport_auth_page():
    with patch(
        "app.services.auth_redirect.pop_for_oauth",
        new=AsyncMock(return_value="/sport/business/dashboard"),
    ):
        url = asyncio.run(failure_page_url("yandex", "state", "yandex"))

    assert url == "/sport/login?error=yandex&redirect=%2Fsport%2Fbusiness%2Fdashboard"


def test_sport_status_page_uses_sport_navigation():
    page = render_status_page(500, "Ошибка", "Обновите страницу.", sport=True)

    assert '<body class="sport-directory">' in page
    assert "Руми Спорт" in page
    assert 'href="/sport/clubs"' in page
    assert 'href="/salons"' not in page


def test_sport_business_dashboard_renders_status_and_role_cards():
    organization = SportOrganization(
        slug="club-test",
        name="Клуб Тест",
        city="Томск",
        description="",
        is_published=True,
        moderation_status="approved",
    )
    page = render_sport_business_dashboard_page(None, [(organization, "owner")])

    assert '<body class="sport-directory rumi-sport">' in page
    assert "sport-business-dashboard__card" in page
    assert "Опубликован" in page
    assert "Владелец" in page
    assert 'href="/sport/club-test/admin"' in page


def test_sport_manifest_page_renders_sport_design():
    from app.web.pages.sport_about import render_sport_about_page
    page = render_sport_about_page()

    assert '<body class="sport-directory sport-about">' in page
    assert "Манифест | Руми Спорт" in page
    assert "Мы убрали из спорта всё лишнее. Остались <em>вы и тренер</em>." in page
    assert 'href="/sport/clubs"' in page
    assert "Найти клуб" in page
    assert "Мы стали партнёрами Т-Банка" in page


def test_sport_profile_has_no_modeling():
    from app.web.pages.profile import render_profile_page
    user = SimpleNamespace(
        id=1,
        full_name="Спорт Клиент",
        phone="+79991112233",
        email="sport@client.ru",
        city="Москва",
        avatar_url="",
        role=SimpleNamespace(value="client"),
        created_at=None,
        is_model=True,
    )
    page = render_profile_page(user, sport=True)

    assert '<body class="page-body sport-directory">' in page
    assert "Мой профиль — Руми Спорт" in page
    assert 'href="/sport/profile"' in page
    assert 'href="/sport/bookings"' in page
    assert 'href="/sport/favorites"' in page
    assert "Статус «Модель»" not in page
    assert "Стать моделью" not in page

