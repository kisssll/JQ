# app/web/pages/register_gym.py
import html

from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.styles import get_base_styles
from app.web.components.yandex_maps import render_yandex_maps_script, yandex_maps_enabled
from app.web.cities import DEFAULT_CITY, city_options_html
from app.web.pages.legal import LEGAL_VERSION


def render_register_gym_page(user=None, error: str = "") -> str:
    """Страница регистрации нового спортивного зала / клуба (заявка)."""

    error_banner = ""
    if error:
        error_banner = (
            f'<div style="background:var(--color-danger-light);color:var(--color-danger);padding:0.75rem 1rem;'
            f'border-radius:var(--radius-16);margin-bottom:1.5rem;font-size:0.9rem;">'
            f'{html.escape(error)}</div>'
        )

    geocoding = yandex_maps_enabled()
    address_geo_attrs = (
        ' id="gymAddressInput" class="address-geocode" autocomplete="off"'
        ' data-lat-field="gymLat" data-lon-field="gymLon" data-map-id="gymAddressMap"'
        if geocoding else ""
    )
    address_hidden_coords = (
        '<input type="hidden" name="latitude" id="gymLat">'
        '<input type="hidden" name="longitude" id="gymLon">'
        if geocoding else ""
    )
    address_map_block = (
        '<div id="gymAddressMap" style="display:none;height:220px;border-radius:var(--radius-16);margin-bottom:1.5rem;overflow:hidden"></div>'
        if geocoding else ""
    )
    address_hint = (
        '<p class="text-muted" style="font-size:0.8rem;margin:-1rem 0 1rem">Начните печатать и выберите вариант из подсказок — так мы точно определим адрес на карте.</p>'
        if geocoding else ""
    )

    city_options = city_options_html(DEFAULT_CITY)

    html_content = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Добавить спортивный клуб — Руми Спорт</title>
    {get_base_styles()}
    {render_yandex_maps_script()}
</head>
<body class="sport-directory rumi-sport">
    {render_header("sport_business", user)}
    
    <main style="padding-top: 5rem;">
        <div class="section-container">
            <div class="card" style="max-width: 600px; margin: 0 auto;">
                <p class="sport-page-eyebrow" style="margin-bottom: 0.5rem;">Руми Спорт · для бизнеса</p>
                <h1 class="text-display" style="font-size: 1.75rem; margin-bottom: 0.5rem;">Добавить спортивный клуб</h1>
                <p class="text-muted" style="margin-bottom: 2rem;">Заполните информацию о вашем клубе или зале. После проверки он появится в каталоге, и вы сможете настраивать расписание, залы и тренеров.</p>

                {error_banner}
                <form action="/api/v1/sport/business/apply" method="post">
                    <label style="display: block; font-weight: 500; margin-bottom: 0.5rem; color: var(--color-heading);">Название клуба или зала *</label>
                    <input type="text" name="name" required placeholder="Например: Спортивный клуб «Атлетика»" style="width: 100%; padding: 0.75rem; border: 1px solid var(--color-border); border-radius: var(--radius-16); font-size: 0.95rem; margin-bottom: 1.5rem;">
                    
                    <label style="display: block; font-weight: 500; margin-bottom: 0.5rem; color: var(--color-heading);">Коротко о клубе</label>
                    <textarea name="description" rows="3" placeholder="Опишите направления, залы, возрастные группы и особенности..." style="width: 100%; padding: 0.75rem; border: 1px solid var(--color-border); border-radius: var(--radius-16); font-size: 0.95rem; margin-bottom: 1.5rem; resize: vertical;"></textarea>
                    
                    <label style="display: block; font-weight: 500; margin-bottom: 0.5rem; color: var(--color-heading);">Город *</label>
                    <select name="city" class="custom-select city-select" required style="margin-bottom: 1.5rem;">
                        {city_options}
                    </select>

                    <label style="display: block; font-weight: 500; margin-bottom: 0.5rem; color: var(--color-heading);">Адрес основного зала *</label>
                    <input type="text" name="address" required placeholder="Улица, дом" style="width: 100%; padding: 0.75rem; border: 1px solid var(--color-border); border-radius: var(--radius-16); font-size: 0.95rem; margin-bottom: 0.5rem;"{address_geo_attrs}>
                    {address_hint}
                    {address_map_block}
                    {address_hidden_coords}

                    <label style="display: block; font-weight: 500; margin-bottom: 0.5rem; color: var(--color-heading);">Телефон для связи *</label>
                    <input type="tel" name="phone" value="+7" required placeholder="+7XXXXXXXXXX" style="width: 100%; padding: 0.75rem; border: 1px solid var(--color-border); border-radius: var(--radius-16); font-size: 0.95rem; margin-bottom: 1.5rem;">

                    <label style="display: block; font-weight: 500; margin-bottom: 0.5rem; color: var(--color-heading);">Почта клуба</label>
                    <input type="email" name="email" placeholder="club@example.com (необязательно)" style="width: 100%; padding: 0.75rem; border: 1px solid var(--color-border); border-radius: var(--radius-16); font-size: 0.95rem; margin-bottom: 0.4rem;">
                    <p class="text-muted" style="font-size: 0.8rem; margin: 0 0 1.5rem;">На неё будут приходить уведомления о новых заявках клиентов и данные доступа сотрудников.</p>

                    <div class="consent-block">
                        <label class="consent-check">
                            <input type="checkbox" name="offer_accepted" value="1" class="consent-check-input" required>
                            <span class="consent-check-text">Я принимаю условия оферты и договора-присоединения, изложенные в
                                <a href="/sport/legal/license" target="_blank" rel="noopener">Условиях для спортивных клубов</a>.</span>
                        </label>
                        <label class="consent-check" style="margin-top: 0.6rem;">
                            <input type="checkbox" name="pd_consent" value="1" class="consent-check-input" required>
                            <span class="consent-check-text">Я даю согласие на обработку персональных данных на условиях
                                <a href="/sport/legal/consent" target="_blank" rel="noopener">Согласия</a>.</span>
                        </label>
                        <input type="hidden" name="consent_version" value="{LEGAL_VERSION}">
                        <p class="consent-note">Доступ к работе открывается после подтверждения заявки платформой.
                            Как мы обрабатываем данные — в
                            <a href="/sport/legal/privacy" target="_blank" rel="noopener">Политике</a>.</p>
                    </div>

                    <button type="submit" class="btn-primary" style="width: 100%; padding: 1rem; font-size: 1rem;">Отправить заявку</button>
                </form>

                <p class="text-muted" style="text-align: center; margin-top: 1rem; font-size: 0.8rem;">Клуб появится в каталоге и станет доступен для записи после проверки модератором.</p>
            </div>
        </div>
        {render_footer(user, sport=True)}
    </main>
</body>
</html>"""

    return html_content
