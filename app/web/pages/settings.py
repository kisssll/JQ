# app/web/pages/settings.py
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.components.icons import (
    ICON_PALETTE,
    ICON_BELL,
    ICON_EDIT_DATA,
    ICON_PHONE_FILLED,
    ICON_MAIL_FILLED,
    ICON_MAP_PIN_FILLED,
    ICON_LOCK_FILLED,
    ICON_TRASH,
    ICON_CHEVRON_DOWN,
    ICON_SETTINGS_GEAR,
)

def render_settings_page(user=None) -> str:
    """Страница настроек."""
    
    phone = (user.phone if user else "") or "+7"
    email = user.email if user else ""
    city = getattr(user, 'city', "") if user else ""

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Настройки — руми</title>
    {get_base_styles()}
</head>
<body>
    {render_header("settings")}
    {render_sidebar("settings", user)}
    
    <main class="settings-main">
        <div class="section-container settings-container">
            <div class="settings-header">
                <span class="settings-header-icon">{ICON_SETTINGS_GEAR}</span>
                <h1 class="text-display settings-title">Настройки</h1>
            </div>
            
            <!-- Тема -->
            <div class="settings-card">
                <h2 class="settings-card-title">
                    <span class="settings-icon-wrapper">{ICON_PALETTE}</span>
                    Тема
                </h2>
                <div class="settings-theme-toggle">
                    <button class="theme-btn active" data-theme="light">☀️ Светлая</button>
                    <button class="theme-btn" data-theme="dark">🌙 Тёмная</button>
                </div>
                <p class="settings-card-hint">Выберите оформление интерфейса.</p>
            </div>
            
            <!-- Уведомления -->
            <div class="settings-card">
                <h2 class="settings-card-title">
                    <span class="settings-icon-wrapper">{ICON_BELL}</span>
                    Уведомления
                </h2>
                <div class="settings-notification-group">
                    <div class="settings-switch-item">
                        <label class="settings-switch">
                            <input type="checkbox" checked id="notify-bookings">
                            <span class="settings-slider"></span>
                        </label>
                        <span>Напоминания о записях</span>
                    </div>
                    <div class="settings-switch-item">
                        <label class="settings-switch">
                            <input type="checkbox" checked id="notify-promotions">
                            <span class="settings-slider"></span>
                        </label>
                        <span>Новые акции салонов</span>
                    </div>
                </div>
                <div class="settings-select-group">
                    <label for="notify-method">Способ получения:</label>
                    <select id="notify-method" class="settings-select custom-select">
                        <option value="email">Email</option>
                        <option value="vk">VK</option>
                        <option value="telegram">Telegram</option>
                    </select>
                </div>
            </div>
            
            <!-- Смена данных (аккордеон) -->
            <div class="settings-card">
                <h2 class="settings-card-title">
                    <span class="settings-icon-wrapper">{ICON_EDIT_DATA}</span>
                    Смена данных
                </h2>
                <div class="settings-accordion">
                    <!-- Телефон -->
                    <div class="accordion-item">
                        <button class="accordion-header" data-target="accordion-phone">
                            <span class="accordion-icon">{ICON_PHONE_FILLED}</span>
                            <span class="accordion-label">Сменить телефон</span>
                            <span class="accordion-chevron">{ICON_CHEVRON_DOWN}</span>
                        </button>
                        <div class="accordion-body" id="accordion-phone">
                            <form class="accordion-form" data-type="phone">
                                <div class="settings-form-group">
                                    <label for="settings-phone">Новый телефон</label>
                                    <input type="tel" id="settings-phone" name="phone" value="{phone}" placeholder="+7XXXXXXXXXX" required>
                                </div>
                                <button type="submit" class="btn-primary settings-save-btn">Сохранить</button>
                            </form>
                        </div>
                    </div>
                    
                    <!-- Город -->
                    <div class="accordion-item">
                        <button class="accordion-header" data-target="accordion-city">
                            <span class="accordion-icon">{ICON_MAP_PIN_FILLED}</span>
                            <span class="accordion-label">Сменить город</span>
                            <span class="accordion-chevron">{ICON_CHEVRON_DOWN}</span>
                        </button>
                        <div class="accordion-body" id="accordion-city">
                            <form class="accordion-form" data-type="city">
                                <div class="settings-form-group">
                                    <label for="settings-city">Новый город</label>
                                    <input type="text" id="settings-city" name="city" value="{city}" placeholder="Москва" required>
                                </div>
                                <button type="submit" class="btn-primary settings-save-btn">Сохранить</button>
                            </form>
                        </div>
                    </div>
                    
                    <!-- Email -->
                    <div class="accordion-item">
                        <button class="accordion-header" data-target="accordion-email">
                            <span class="accordion-icon">{ICON_MAIL_FILLED}</span>
                            <span class="accordion-label">Сменить email</span>
                            <span class="accordion-chevron">{ICON_CHEVRON_DOWN}</span>
                        </button>
                        <div class="accordion-body" id="accordion-email">
                            <form class="accordion-form" data-type="email">
                                <div class="settings-form-group">
                                    <label for="settings-email">Новый email</label>
                                    <input type="email" id="settings-email" name="email" value="{email}" placeholder="example@mail.ru" required>
                                </div>
                                <button type="submit" class="btn-primary settings-save-btn">Сохранить</button>
                            </form>
                        </div>
                    </div>
                    
                    <!-- Пароль -->
                    <div class="accordion-item">
                        <button class="accordion-header" data-target="accordion-password">
                            <span class="accordion-icon">{ICON_LOCK_FILLED}</span>
                            <span class="accordion-label">Сменить пароль</span>
                            <span class="accordion-chevron">{ICON_CHEVRON_DOWN}</span>
                        </button>
                        <div class="accordion-body" id="accordion-password">
                            <form class="accordion-form" data-type="password">
                                <div class="settings-form-group">
                                    <label for="settings-current-password">Текущий пароль</label>
                                    <input type="password" id="settings-current-password" name="current_password" required>
                                </div>
                                <div class="settings-form-group">
                                    <label for="settings-new-password">Новый пароль</label>
                                    <input type="password" id="settings-new-password" name="new_password" required>
                                </div>
                                <div class="settings-form-group">
                                    <label for="settings-confirm-password">Подтвердите пароль</label>
                                    <input type="password" id="settings-confirm-password" name="confirm_password" required>
                                </div>
                                <button type="submit" class="btn-primary settings-save-btn">Сохранить</button>
                            </form>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Удаление аккаунта.
                 Было: кнопка без формы, JS спрашивал пароль через prompt() и
                 показывал «Аккаунт удалён (имитация)», ничего не удаляя.
                 Теперь та же форма и тот же эндпоинт, что в профиле, и текст
                 описывает то, что происходит на самом деле: эндпоинт снимает
                 is_active, данные остаются. Подтверждение — общий диалог по
                 data-confirm, отдельный JS больше не нужен. -->
            <div class="settings-delete-section">
                <p class="settings-delete-warning">Аккаунт будет деактивирован: вы выйдете из системы и не сможете войти. Данные сохраняются — для восстановления или полного удаления обратитесь в поддержку.</p>
                <form action="/api/v1/users/me/delete-form" method="post" class="settings-delete-form"
                      data-confirm="Деактивировать аккаунт?" data-confirm-label="Деактивировать">
                    <div class="settings-form-group">
                        <label for="settings-delete-password">Подтвердите паролем</label>
                        <input type="password" id="settings-delete-password" name="password" placeholder="Ваш пароль" required>
                    </div>
                    <button type="submit" class="btn-outline settings-delete-btn" id="delete-account-btn">
                        <span class="settings-icon-sm">{ICON_TRASH}</span>
                        Деактивировать аккаунт
                    </button>
                </form>
            </div>
            
        </div>
        {render_footer(user)}
    </main>
</body>
</html>"""
    return html