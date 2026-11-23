"""Переходы проверяются с обычной банкой cookie, раздельной для каждого хоста."""
from urllib.parse import parse_qs, urlsplit

import pytest

from app.core.config import settings
from tests.conftest import register_user
from tests.test_auth_vk import _mock_vk
from tests.test_auth_yandex import _mock_yandex

BEAUTY = "https://staging.rrumi.ru"
SPORT = "https://sport-staging.rrumi.ru"
CLUB = "/sport/sparta/schedule?day=2&tag=a%2Bb&tag=b"


@pytest.fixture(autouse=True)
def hosts(monkeypatch):
    monkeypatch.setattr(settings, "BEAUTY_HOST", urlsplit(BEAUTY).netloc)
    monkeypatch.setattr(settings, "SPORT_HOST", urlsplit(SPORT).netloc)
    monkeypatch.setattr(settings, "COOKIE_SECURE", True)


async def test_old_guest_link_preserves_exact_target(client):
    response = await client.get(BEAUTY + CLUB)
    assert response.headers["location"] == SPORT + CLUB
    assert not response.cookies
    assert (await client.get("https://rrumi.ru/directions/start")).status_code == 404


@pytest.mark.parametrize("source,other", [(BEAUTY, SPORT), (SPORT, BEAUTY)])
async def test_session_round_trip_and_logout(client, source, other):
    phone = "+79991113567"
    await register_user(client, phone)
    await client.post(source + "/api/v1/auth/login-web", data={"phone": phone, "password": "Testpass1"})
    for origin, dest in [(source, other), (other, source)]:
        path = CLUB if dest == SPORT else "/directions/beauty"
        response = await client.get(origin + path, follow_redirects=True)
        assert str(response.url) == dest + (CLUB if dest == SPORT else "/")
        assert (await client.get(dest + "/api/v1/users/me")).json()["phone"] == phone
        cookies = list(client.cookies.jar)
        assert all(c.secure and not c.domain_specified for c in cookies)
        assert not any(c.name.startswith("__Host-rumi-direction") for c in cookies)
    assert (await client.get("https://rrumi.ru/api/v1/users/me")).status_code == 401
    path = "/sport/logout" if source == SPORT else "/logout"
    response = await client.get(source + path)
    assert (await client.get(other + "/api/v1/users/me")).status_code == 401
    await client.get(response.headers["location"], follow_redirects=True)
    assert not list(client.cookies.jar)


@pytest.mark.parametrize("provider", ["vk", "yandex"])
async def test_provider_uses_registered_callback_and_returns_to_club(client, monkeypatch, provider):
    monkeypatch.setattr(settings, provider.upper() + "_OAUTH_ENABLED", True)
    if provider == "vk":
        _mock_vk(monkeypatch, {"phone": "79991113568", "first_name": "Тест"})
    else:
        _mock_yandex(monkeypatch, {"default_phone": {"number": "79991113568"}})
    start = await client.get(SPORT + f"/api/v1/auth/{provider}/start", params={"redirect": CLUB})
    response = await client.get(start.headers["location"])
    params = parse_qs(urlsplit(response.headers["location"]).query)
    callback = params["redirect_uri"][0]
    assert callback == BEAUTY + f"/api/v1/auth/{provider}/callback"
    response = await client.get(callback, params={"state": params["state"][0], "code": "test", "device_id": "test"},
                                follow_redirects=True)
    assert str(response.url) == SPORT + CLUB
    assert (await client.get(SPORT + "/api/v1/users/me")).json()["phone"] == "+79991113568"


async def test_grant_is_bound_to_browser_and_single_use(client):
    from app.core.security import create_access_token

    client.cookies.set("access_token", create_access_token(1), domain=urlsplit(BEAUTY).hostname)
    response = await client.get(SPORT + "/directions/start", params={"next": CLUB})
    proof = next(cookie for cookie in client.cookies.jar if cookie.name.startswith("__Host-"))
    response = await client.get(response.headers["location"])
    finish = response.headers["location"]
    client.cookies.delete(proof.name, domain=proof.domain)
    assert (await client.get(finish)).status_code == 400
    client.cookies.jar.set_cookie(proof)
    assert (await client.get(finish)).status_code == 400
    assert client.cookies.get("access_token", domain=urlsplit(SPORT).hostname) is None
