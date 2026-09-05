# app/web/components/styles.py
import hashlib
import html
import os

from app.core.config import settings

# Vite собирает бандл с ФИКСИРОВАННЫМИ именами (main.js/main.css, см. vite.config.js),
# а StaticFiles не шлёт Cache-Control → браузеры эвристически кэшируют старый файл
# без ревалидации. После деплоя URL тот же, содержимое другое → у разных людей
# разные закэшированные версии staging. Лечим cache-busting'ом: ?v=<хэш содержимого>
# меняется при каждой пересборке, между деплоями браузер спокойно кэширует.
_DIST_DIR = "static/dist"


def _asset_version(filename: str) -> str:
    try:
        with open(os.path.join(_DIST_DIR, filename), "rb") as f:
            return hashlib.md5(f.read()).hexdigest()[:10]
    except OSError:
        return "dev"


# Считаем один раз при импорте = при старте контейнера = отражает задеплоенный бандл.
_CSS_V = _asset_version("main.css")
_JS_V = _asset_version("main.js")


def _metrika_meta() -> str:
    """Номер счётчика Метрики — тегом meta, а не самим счётчиком.

    Сам тег Метрики в разметку не попадает никогда: п. 2.3 Политики cookie
    разрешает аналитику только после согласия, поэтому скрипт подставляет
    cookie-notice.js, и только когда человек выбрал «Принять». Здесь мы лишь
    сообщаем фронтенду номер — если он вообще задан.
    """
    counter = (settings.YANDEX_METRIKA_ID or "").strip()
    if not counter:
        return ""
    return f'<meta name="ym-counter" content="{html.escape(counter, quote=True)}">'


def get_base_styles() -> str:
    """HTML-теги подключения собранного CSS/JS-бандла (с cache-busting по хэшу)
    + PWA-теги (manifest, тема, apple-touch) для установки на экран смартфона."""
    return f"""
    <script>(function(){{try{{var t=localStorage.getItem('theme');if(t)document.documentElement.setAttribute('data-theme',t);}}catch(e){{}}}})();</script>
    {_metrika_meta()}
    <link rel="stylesheet" href="/static/dist/main.css?v={_CSS_V}">
    <script type="module" src="/static/dist/main.js?v={_JS_V}"></script>
    <link rel="manifest" href="/manifest.webmanifest">
    <meta name="theme-color" content="#c081b8">
    <link rel="icon" type="image/png" sizes="32x32" href="/static/icons/favicon-32.png">
    <link rel="icon" type="image/png" sizes="16x16" href="/static/icons/favicon-16.png">
    <link rel="icon" type="image/png" sizes="96x96" href="/static/icons/favicon-96.png">
    <link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="Руми">
    """
