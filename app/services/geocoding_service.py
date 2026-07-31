# app/services/geocoding_service.py
"""Серверное геокодирование через HTTP Геокодер Яндекса — только для
сценариев без участия пользователя (разовый бэкфилл старых салонов,
app/scripts/geocode_salons.py). Живые формы (регистрация/редактирование
салона) получают координаты от клиента напрямую через JS-виджет подсказок
(static/src/js/address-geocoder.js) — туда этот сервис не участвует.
"""
from typing import Optional

import httpx

from app.core.config import settings

GEOCODER_URL = "https://geocode-maps.yandex.ru/1.x/"


class GeocodingError(Exception):
    """Сбой запроса к геокодеру (сеть, ключ, неожиданный формат ответа)."""


async def geocode_address(address: str) -> Optional[tuple[float, float]]:
    """(latitude, longitude) для адреса, либо None если Яндекс ничего не нашёл."""
    if not settings.YANDEX_MAPS_API_KEY:
        raise GeocodingError("YANDEX_MAPS_API_KEY не задан")

    params = {
        "apikey": settings.YANDEX_MAPS_API_KEY,
        "geocode": address,
        "format": "json",
        "results": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(GEOCODER_URL, params=params)
    except httpx.HTTPError as e:
        raise GeocodingError(f"Сеть/таймаут при обращении к геокодеру: {e}")

    if response.status_code != 200:
        raise GeocodingError(f"Геокодер вернул {response.status_code}: {response.text[:200]}")

    data = response.json()
    try:
        members = data["response"]["GeoObjectCollection"]["featureMember"]
    except (KeyError, TypeError):
        raise GeocodingError("Неожиданный формат ответа геокодера")

    if not members:
        return None

    # pos — строка "долгота широта" через пробел (порядок именно такой у Яндекса).
    pos = members[0]["GeoObject"]["Point"]["pos"]
    lon_str, lat_str = pos.split(" ")
    return float(lat_str), float(lon_str)
