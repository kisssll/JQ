# app/web/components/yandex_maps.py
"""Подключение JS API Яндекс.Карт (подсказки адреса + мини-карта) — общий
хелпер для всех форм с полем адреса и для публичной страницы салона.

Пусто без ключа (YANDEX_MAPS_API_KEY, см. app/core/config.py) — тогда
подсказки/карта просто не подключаются, поле адреса остаётся обычным
текстовым без обязательных координат (дефолт для локальной разработки и
тестов, где ключа нет)."""
from app.core.config import settings


def yandex_maps_enabled() -> bool:
    return bool(settings.YANDEX_MAPS_API_KEY)


def render_yandex_maps_script() -> str:
    """Тег подключения classic JS API 2.1 (подсказки + Map/Placemark) —
    выбран вместо новой Web Components API v3 как более простой и
    задокументированный вариант для процедурного JS без сборки."""
    if not yandex_maps_enabled():
        return ""
    return (
        f'<script src="https://api-maps.yandex.ru/2.1/?apikey={settings.YANDEX_MAPS_API_KEY}'
        f'&lang=ru_RU" type="text/javascript"></script>'
    )
