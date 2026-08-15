# app/web/pages/register_salon.py
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.components.yandex_maps import render_yandex_maps_script, yandex_maps_enabled
from app.web.cities import RUSSIAN_CITIES, DEFAULT_CITY


def render_register_salon_page(user=None, error: str = "") -> str:
    """Страница регистрации нового салона (заявка)."""

    error_banner = ""
    if error:
        import html as _html
        error_banner = (
            f'<div style="background:#fde8e8;color:#c0392b;padding:0.75rem 1rem;'
            f'border-radius:0.75rem;margin-bottom:1.5rem;font-size:0.9rem;">'
            f'{_html.escape(error)}</div>'
        )

    # Подсказки адреса + мини-карта — только если задан YANDEX_MAPS_API_KEY
    # (см. app/core/config.py). Без ключа поле остаётся обычным текстом.
    geocoding = yandex_maps_enabled()
    address_geo_attrs = (
        ' id="salonAddressInput" class="address-geocode" autocomplete="off"'
        ' data-lat-field="salonLat" data-lon-field="salonLon" data-map-id="salonAddressMap"'
        if geocoding else ""
    )
    address_hidden_coords = (
        '<input type="hidden" name="latitude" id="salonLat">'
        '<input type="hidden" name="longitude" id="salonLon">'
        if geocoding else ""
    )
    address_map_block = (
        '<div id="salonAddressMap" style="display:none;height:220px;border-radius:0.75rem;margin-bottom:1.5rem;overflow:hidden"></div>'
        if geocoding else ""
    )
    address_hint = (
        '<p class="text-muted" style="font-size:0.8rem;margin:-1rem 0 1rem">Начните печатать и выберите вариант из подсказок — так мы точно определим адрес на карте.</p>'
        if geocoding else ""
    )

    city_options = "".join(
        f'<option value="{c}"{" selected" if c == DEFAULT_CITY else ""}>{c}</option>' for c in RUSSIAN_CITIES
    )

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Добавить салон — руми</title>
    {get_base_styles()}
    {render_yandex_maps_script()}
</head>
<body>
    {render_header("business")}
    {render_sidebar("business", user)}
    
    <main style="margin-right: 16rem; padding-top: 2rem;">
        <div class="section-container">
            <div class="card" style="max-width: 600px; margin: 0 auto;">
                <h1 class="text-display" style="font-size: 1.75rem; margin-bottom: 0.5rem;">Добавить салон</h1>
                <p class="text-muted" style="margin-bottom: 2rem;">Заполните информацию о вашем салоне. После проверки он появится в каталоге.</p>

                {error_banner}
                <form action="/api/v1/business/my-salon" method="post">
                    <label style="display: block; font-weight: 500; margin-bottom: 0.5rem; color: var(--color-heading);">Название салона *</label>
                    <input type="text" name="name" required placeholder="Например: Студия красоты «Лотос»" style="width: 100%; padding: 0.75rem; border: 1px solid var(--color-border); border-radius: 0.75rem; font-size: 0.95rem; margin-bottom: 1.5rem;">
                    
                    <label style="display: block; font-weight: 500; margin-bottom: 0.5rem; color: var(--color-heading);">Описание</label>
                    <textarea name="description" rows="3" placeholder="Опишите ваш салон, услуги, особенности..." style="width: 100%; padding: 0.75rem; border: 1px solid var(--color-border); border-radius: 0.75rem; font-size: 0.95rem; margin-bottom: 1.5rem; resize: vertical;"></textarea>
                    
                    <label style="display: block; font-weight: 500; margin-bottom: 0.5rem; color: var(--color-heading);">Город *</label>
                    <select name="city" required style="width: 100%; padding: 0.75rem; border: 1px solid var(--color-border); border-radius: 0.75rem; font-size: 0.95rem; margin-bottom: 1.5rem;">
                        {city_options}
                    </select>

                    <label style="display: block; font-weight: 500; margin-bottom: 0.5rem; color: var(--color-heading);">Адрес *</label>
                    <input type="text" name="address" required placeholder="Улица, дом" style="width: 100%; padding: 0.75rem; border: 1px solid var(--color-border); border-radius: 0.75rem; font-size: 0.95rem; margin-bottom: 0.5rem;"{address_geo_attrs}>
                    {address_hint}
                    {address_map_block}
                    {address_hidden_coords}

                    <label style="display: block; font-weight: 500; margin-bottom: 0.5rem; color: var(--color-heading);">Телефон *</label>
                    <input type="tel" name="phone" value="+7" required placeholder="+7XXXXXXXXXX" style="width: 100%; padding: 0.75rem; border: 1px solid var(--color-border); border-radius: 0.75rem; font-size: 0.95rem; margin-bottom: 1.5rem;">

                    <label style="display: block; font-weight: 500; margin-bottom: 0.5rem; color: var(--color-heading);">Почта салона</label>
                    <input type="email" name="email" placeholder="salon@example.com (необязательно)" style="width: 100%; padding: 0.75rem; border: 1px solid var(--color-border); border-radius: 0.75rem; font-size: 0.95rem; margin-bottom: 0.4rem;">
                    <p class="text-muted" style="font-size: 0.8rem; margin: 0 0 1.5rem;">На неё можно отправлять реквизиты новых сотрудников и получать уведомления о записях.</p>

                    <label style="display: flex; gap: 0.6rem; align-items: flex-start; margin-bottom: 1.5rem; font-size: 0.85rem; cursor: pointer;" class="text-muted">
                        <input type="checkbox" name="offer_accepted" value="1" required style="margin-top: 0.2rem; flex-shrink: 0;">
                        <span>Я принимаю условия оферты и договора-присоединения, даю согласие на обработку персональных данных. Доступ к работе открывается после подтверждения заявки платформой.</span>
                    </label>

                    <button type="submit" class="btn-primary" style="width: 100%; padding: 1rem; font-size: 1rem;">Отправить заявку</button>
                </form>

                <p class="text-muted" style="text-align: center; margin-top: 1rem; font-size: 0.8rem;">Салон появится в каталоге и станет доступен для записи после проверки модератором.</p>
            </div>
        </div>
        {render_footer(user)}
    </main>
</body>
</html>"""
    
    return html