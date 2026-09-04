# app/web/pages/profile.py
from app.web.components.escaping import e
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.cities import city_options_html
from app.web.components.icons import (
    ICON_USER,
    ICON_CAMERA,
    ICON_PHONE,
    ICON_MAIL,
    ICON_CALENDAR_SMALL,
    ICON_EDIT,
    ICON_MAP_PIN_SMALL,
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
    ICON_BRIEFCASE,
    ICON_BUILDING2,
    ICON_MAP_PIN,
    ICON_MODEL,
    ICON_MOON,
    ICON_STAR_FILLED,
    ICON_SUN,
    ICON_USERS,
)
from app.core.config import settings


def _channels_overview(user, available) -> str:
    """Список каналов связи: что подключено и что с этим можно сделать.

    Раньше управление было размазано — телефон менялся в одном месте, почта
    другой формой, мессенджеры подключались только через /start в боте, а
    отвязать нельзя было вовсе. Здесь всё состояние видно сразу.
    """
    from app.core.config import settings
    from app.models.models import NotifyChannel

    rows = []
    phone = getattr(user, "phone", "") or "—"
    rows.append(("Телефон", phone, "подтверждён", "#22c55e", ""))

    def _messenger_row(channel, title, username, url_tpl):
        connected = channel in available
        if connected:
            action = (
                f'<form method="post" action="/api/v1/users/me/disconnect-channel" style="display:inline">'
                f'<input type="hidden" name="channel" value="{channel.value}">'
                f'<button class="btn-mini" type="submit">Отвязать</button></form>'
            )
            return (title, "подключён", "подключён", "#22c55e", action)
        link = (f'<a class="btn-mini" href="{url_tpl.format(username)}" target="_blank" '
                f'rel="noopener">Подключить</a>') if username else ""
        return (title, "не подключён", "не подключён", "var(--color-muted)", link)

    rows.append(_messenger_row(NotifyChannel.TG, "Telegram", settings.TG_BOT_USERNAME, "https://t.me/{}"))
    rows.append(_messenger_row(NotifyChannel.MAX, "MAX", settings.MAX_BOT_USERNAME, "https://max.ru/{}"))

    email = (getattr(user, "email", "") or "").strip()
    rows.append((
        "Почта", email or "не указана", "указана" if email else "не указана",
        "#22c55e" if email else "var(--color-muted)", "",
    ))

    items = ""
    for title, value, state, color, action in rows:
        items += (
            f'<div style="display:flex;align-items:center;justify-content:space-between;gap:0.75rem;'
            f'padding:0.5rem 0;border-bottom:1px solid var(--color-border)">'
            f'<div><strong>{title}</strong><br>'
            f'<span class="settings-card-hint" style="color:{color}">{value}</span></div>'
            f'<div>{action}</div></div>'
        )
    return (f'<div style="margin-bottom:1rem">{items}'
            f'<p class="settings-card-hint" style="margin:0.5rem 0 0">'
            f'Телефон и почта меняются ниже, в разделе «Смена данных».</p></div>')


def _notify_channel_block(user) -> str:
    """Реальное управление каналом уведомлений.

    Раньше здесь стояла заглушка (чекбоксы и селект email/vk/telegram, ни к
    чему не подключённые). Теперь показываем фактический канал, даём
    переключиться на любой ПОДКЛЮЧЁННЫЙ и мягко зовём подключить, если
    доставлять некуда — блокировать ничего не нужно.
    """
    from app.core.config import settings
    from app.models.models import NotifyChannel
    from app.services.notify_channel import CHANNEL_LABELS, resolve

    if user is None:
        return ""

    channel, _address = resolve(user)
    available = []
    if getattr(user, "tg_chat_id", None):
        available.append(NotifyChannel.TG)
    if getattr(user, "max_chat_id", None):
        available.append(NotifyChannel.MAX)
    if (getattr(user, "email", "") or "").strip():
        available.append(NotifyChannel.EMAIL)

    if not available:
        # Канала нет — мягкий промпт, без запретов
        links = []
        if settings.TG_BOT_USERNAME:
            links.append(
                f'<a class="btn-outline" href="https://t.me/{settings.TG_BOT_USERNAME}" '
                f'target="_blank" rel="noopener">Подключить Telegram</a>'
            )
        if settings.MAX_BOT_USERNAME:
            links.append(
                f'<a class="btn-outline" href="https://max.ru/{settings.MAX_BOT_USERNAME}" '
                f'target="_blank" rel="noopener">Подключить MAX</a>'
            )
        return f"""
            <p class="settings-card-hint" style="margin:0 0 0.75rem">
                Канал уведомлений не подключён — напоминания о записях и важные
                сообщения приходить не будут. Подключите мессенджер или укажите
                почту в разделе «Смена данных».
            </p>
            <div style="display:flex;gap:0.5rem;flex-wrap:wrap">{''.join(links)}</div>"""

    options = "".join(
        f'<option value="{c.value}"{" selected" if c == channel else ""}>{CHANNEL_LABELS[c]}</option>'
        for c in available
    )
    missing = []
    if NotifyChannel.TG not in available and settings.TG_BOT_USERNAME:
        missing.append(
            f'<a href="https://t.me/{settings.TG_BOT_USERNAME}" target="_blank" rel="noopener">Telegram</a>'
        )
    if NotifyChannel.MAX not in available and settings.MAX_BOT_USERNAME:
        missing.append(
            f'<a href="https://max.ru/{settings.MAX_BOT_USERNAME}" target="_blank" rel="noopener">MAX</a>'
        )
    missing_hint = (
        f'<p class="settings-card-hint" style="margin:0.5rem 0 0">Можно подключить ещё: {", ".join(missing)}.</p>'
        if missing else ""
    )

    return f"""
            {_channels_overview(user, available)}
            <form method="post" action="/api/v1/users/me/notify-channel" class="settings-select-group">
                <label for="notify-method">Способ получения:</label>
                <select name="channel" id="notify-method" class="settings-select custom-select">
                    {options}
                </select>
                <button type="submit" class="btn-outline settings-save-btn">Сохранить</button>
            </form>
            <p class="settings-card-hint" style="margin:0.5rem 0 0">
                Сейчас уведомления приходят: <strong>{CHANNEL_LABELS[channel]}</strong>.
            </p>
            {missing_hint}"""


def render_profile_page(user=None, master_profile=None, salon=None, stats=None, error=None, success=None) -> str:
    # Обработка сообщений
    error_message = ""
    success_message = ""
    if error:
        error_messages = {
            "email_taken": "Этот email уже используется другим пользователем",
            "wrong_password": "Неверный текущий пароль",
            "password_mismatch": "Новые пароли не совпадают",
            "password_too_short": "Пароль должен быть не менее 8 символов",
            "phone_exists": "Пользователь с таким телефоном уже зарегистрирован",
            "bad_phone": "Некорректный номер телефона",
            "bad_city": "Выберите город из списка подсказок",
            "phone_not_verified": "Номер не подтверждён — подтвердите его в Telegram",
            "email_not_verified": "Код неверный или истёк — запросите новый",
            "otp_unavailable": "Сервис подтверждения временно недоступен, попробуйте позже",
            "update_failed": "Не удалось обновить профиль",
            "notify_channel_invalid": "Неизвестный канал уведомлений",
            "notify_channel_unavailable": "Этот канал не подключён — сначала привяжите бота или укажите почту",
            "notify_channel_last": "Это единственный канал связи — сначала подключите другой, иначе уведомления перестанут приходить",
        }
        error_message = f'<div class="profile-alert profile-alert-error">{error_messages.get(error, "Произошла ошибка")}</div>'

    if success:
        success_messages = {
            "updated": "Профиль успешно обновлён",
            "password_updated": "Пароль успешно изменён",
            "email_updated": "Email обновлён",
            "city_updated": "Город обновлён",
            "phone_updated": "Телефон обновлён",
            "avatar_updated": "Аватар обновлён",
            "notify_channel_updated": "Канал уведомлений обновлён",
            "notify_channel_disconnected": "Мессенджер отвязан",
        }
        success_message = f'<div class="profile-alert profile-alert-success">{success_messages.get(success, "Операция выполнена успешно")}</div>'

    if not user:
        return _render_guest_page()

    # Общие данные
    name = user.full_name or "Пользователь"
    phone = user.phone or "+7"
    email = user.email or ""
    city = getattr(user, "city", "") or "Не указан"
    avatar_url = user.avatar_url or ""
    role = user.role.value if user.role else "client"
    created_at = getattr(user, "created_at", None)
    member_since = created_at.strftime("%d.%m.%Y") if created_at else ""
    avatar_letter = name[0].upper() if name else "?"

    role_names = {
        "client": "Клиент",
        "model": "Модель",
        "master": "Мастер",
        "business": "Владелец салона",
        "admin": "Администратор",
    }
    role_display = role_names.get(role, role.capitalize())

    # Ролевой блок
    role_block = ""

    if role == "master" and master_profile:
        spec = master_profile.specialization or "—"
        exp = master_profile.experience_years or 0
        rating = master_profile.rating or 0
        bio = master_profile.bio or ""
        role_block = f"""
        <div class="profile-role-block profile-master-block">
            <div class="profile-role-header">
                <h3>{ICON_BRIEFCASE} Профессиональная информация</h3>
            </div>
            <div class="profile-role-body">
                <div class="profile-master-grid">
                    <div>
                        <span class="profile-label">Специализация</span>
                        <span class="profile-value">{spec}</span>
                    </div>
                    <div>
                        <span class="profile-label">Опыт</span>
                        <span class="profile-value">{exp} лет</span>
                    </div>
                    <div>
                        <span class="profile-label">Рейтинг</span>
                        <span class="profile-value">{ICON_STAR_FILLED} {rating}</span>
                    </div>
                </div>
                {f'<div class="profile-master-bio">{bio}</div>' if bio else ''}
                <a href="/master/schedule" class="profile-btn-secondary">Моё расписание →</a>
            </div>
        </div>
        """

    elif role == "business" and salon:
        salon_name = salon.name or "—"
        salon_address = salon.address or "—"
        salon_phone = salon.phone or "—"
        salon_rating = salon.rating or 0
        salon_reviews = salon.reviews_count or 0
        masters_count = getattr(salon, "masters_count", 0)
        role_block = f"""
        <div class="profile-role-block profile-business-block">
            <div class="profile-role-header">
                <h3>{ICON_BUILDING2} Мой салон</h3>
            </div>
            <div class="profile-role-body">
                <div class="profile-business-name">{e(salon_name)}</div>
                <div class="profile-business-meta">
                    <span>{ICON_MAP_PIN} {salon_address}</span>
                    <span>{ICON_PHONE} {salon_phone}</span>
                </div>
                <div class="profile-business-stats">
                    <span>{ICON_STAR_FILLED} {salon_rating} ({salon_reviews} отзывов)</span>
                    <span>{ICON_USERS} {masters_count} мастеров</span>
                </div>
                <a href="/business/dashboard" class="profile-btn-secondary">Панель управления →</a>
            </div>
        </div>
        """

    # «Модель» — аддитивный статус поверх обычной роли (не сама role), поэтому
    # блок считается независимо от role_block и может показываться вместе с ним.
    is_model = bool(getattr(user, "is_model", False))
    if is_model:
        model_photo = getattr(user, "model_photo_url", None) or ""
        model_bio = getattr(user, "model_bio", "") or ""
        moderation = getattr(user, "model_moderation_status", None)
        moderation_value = moderation.value if moderation else "pending"
        moderation_badges = {
            "pending": '<span class="profile-model-status" style="display:inline-block;padding:0.2rem 0.6rem;border-radius:1rem;font-size:0.75rem;font-weight:600;background:#fef3c7;color:#92400e;margin-bottom:0.5rem">На модерации</span>',
            "approved": '<span class="profile-model-status" style="display:inline-block;padding:0.2rem 0.6rem;border-radius:1rem;font-size:0.75rem;font-weight:600;background:#d1fae5;color:#065f46;margin-bottom:0.5rem">Одобрена</span>',
            "rejected": '<span class="profile-model-status" style="display:inline-block;padding:0.2rem 0.6rem;border-radius:1rem;font-size:0.75rem;font-weight:600;background:#fee2e2;color:#991b1b;margin-bottom:0.5rem">Отклонена</span>',
        }
        rejection_reason = getattr(user, "model_rejection_reason", "") or ""
        model_block = f"""
        <div class="profile-role-block profile-model-block">
            <div class="profile-role-header">
                <h3>{ICON_MODEL} Статус «Модель»</h3>
            </div>
            <div class="profile-role-body">
                {moderation_badges.get(moderation_value, "")}
                {f'<p class="text-muted" style="font-size:0.85rem;margin-bottom:0.5rem">Причина: {rejection_reason}</p>' if moderation_value == "rejected" and rejection_reason else ''}
                {f'<img src="{model_photo}" alt="" loading="lazy" style="width:64px;height:64px;border-radius:50%;object-fit:cover;margin-bottom:0.5rem">' if model_photo else ''}
                {f'<p style="margin-bottom:0.5rem">{model_bio}</p>' if model_bio else ''}
                <a href="/model/dashboard" class="profile-btn-secondary">Лента и мои мэтчи →</a>
                <a href="/model/join" class="profile-btn-secondary">Редактировать анкету →</a>
            </div>
        </div>
        """
    else:
        model_block = f"""
        <div class="profile-role-block profile-model-block">
            <div class="profile-role-header">
                <h3>{ICON_MODEL} Стать моделью</h3>
            </div>
            <div class="profile-role-body">
                <p class="text-muted" style="margin-bottom:0.75rem">Позвольте мастерам отработать на вас технику за скидку или бесплатно — заведите анкету и смотрите, кто ищет модель.</p>
                <a href="/model/join" class="profile-btn-secondary">Стать моделью →</a>
            </div>
        </div>
        """

    # ========== БЛОКИ НАСТРОЕК (без заголовка) ==========
    city_value = getattr(user, "city", "") or ""

    # Смена телефона — только с подтверждением владения новым номером через TG
    # (телефон = логин-идентификатор). Механика та же, что при регистрации:
    # кнопка → /register/tg-start → бот подтверждает → request_id → сабмит.
    # Подтвердить новый номер можно любым рабочим мессенджером — раньше был
    # зашит только Telegram, и владельцы MAX менять телефон не могли вовсе.
    verify_buttons = []
    if settings.TG_VERIFY_ENABLED:
        verify_buttons.append(
            '<button type="button" id="phone-verify-btn" class="btn-outline settings-save-btn phone-verify-btn" '
            'data-start-url="/api/v1/auth/register/tg-start" data-channel="Telegram">Подтвердить в Telegram</button>'
        )
    if settings.MAX_VERIFY_ENABLED:
        verify_buttons.append(
            '<button type="button" class="btn-outline settings-save-btn phone-verify-btn" '
            'data-start-url="/api/v1/auth/register/max-start" data-channel="MAX">Подтвердить в MAX</button>'
        )

    if verify_buttons:
        channels_text = " или ".join(
            b.split('data-channel="')[1].split('"')[0] for b in verify_buttons
        )
        phone_change_block = f"""
                        <form id="phone-change-form" action="/api/v1/users/me/phone-form" method="post">
                            <div class="settings-form-group">
                                <label for="settings-phone">Новый телефон</label>
                                <input type="tel" id="settings-phone" name="phone" value="{phone}" placeholder="+7XXXXXXXXXX" required>
                            </div>
                            <input type="hidden" id="phone-request-id" name="request_id" value="">
                            <!-- Подсказка идёт за полем, а не между кнопками: объяснение,
                                 что делать, попадалось на глаза уже после первого действия.
                                 Так же устроен блок смены email. -->
                            <p class="settings-card-hint" id="phone-verify-hint">Введите новый номер и подтвердите владение им в {channels_text}.</p>
                            <div class="settings-verify-row">{''.join(verify_buttons)}</div>
                            <button type="submit" id="phone-save-btn" class="btn-primary settings-save-btn" disabled>Сохранить</button>
                        </form>"""
    else:
        phone_change_block = '<p class="settings-card-hint">Смена телефона временно недоступна.</p>'

    settings_blocks = f"""
    <!-- Настройки -->
    <div class="profile-settings-wrapper">

        <!-- Тема -->
        <div class="settings-card">
            <h2 class="settings-card-title">
                <span class="settings-icon-wrapper">{ICON_PALETTE}</span>
                Тема
            </h2>
            <div class="settings-theme-toggle">
                <button class="theme-btn active" data-theme="light">{ICON_SUN} Светлая</button>
                <button class="theme-btn" data-theme="dark">{ICON_MOON} Тёмная</button>
            </div>
            <p class="settings-card-hint">Выберите оформление интерфейса.</p>
        </div>

        <!-- Уведомления -->
        <div class="settings-card">
            <h2 class="settings-card-title">
                <span class="settings-icon-wrapper">{ICON_BELL}</span>
                Уведомления
            </h2>
            {_notify_channel_block(user)}
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
                    <div class="accordion-body" id="accordion-phone">{phone_change_block}
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
                        <form action="/api/v1/users/me/city-form" method="post">
                            <div class="settings-form-group">
                                <label for="settings-city">Новый город</label>
                                <select id="settings-city" name="city" class="custom-select city-select">
                                    <option value="">Не указан</option>
                                    {city_options_html(city_value)}
                                </select>
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
                        <form id="email-change-form" action="/api/v1/users/me/email-form" method="post">
                            <div class="settings-form-group">
                                <label for="settings-email">Новый email</label>
                                <input type="email" id="settings-email" name="email" value="{email}" placeholder="example@mail.ru" required>
                            </div>
                            <input type="hidden" id="email-request-id" name="request_id" value="">
                            <!-- Подсказка идёт сразу за полем, а не между кнопками: раньше
                                 порядок был «кнопка → подсказка → кнопка», и объяснение
                                 попадалось на глаза уже после первого действия. -->
                            <p class="settings-card-hint" id="email-verify-hint">Введите новый email и получите на него код подтверждения.</p>
                            <button type="button" id="email-send-code-btn" class="btn-outline settings-save-btn">Отправить код</button>
                            <div class="settings-form-group is-short" id="email-code-group" style="display:none;">
                                <label for="settings-email-code">Код из письма</label>
                                <input type="text" id="settings-email-code" name="code" inputmode="numeric" autocomplete="one-time-code" placeholder="0000">
                            </div>
                            <button type="submit" id="email-save-btn" class="btn-primary settings-save-btn" disabled>Подтвердить и сохранить</button>
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
                        <form action="/api/v1/users/me/password-form" method="post">
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

        <!-- Удаление аккаунта -->
        <div class="settings-delete-section">
            <p class="settings-delete-warning">Аккаунт будет деактивирован: вы выйдете из системы и не сможете войти. Данные сохраняются — для восстановления или полного удаления обратитесь в поддержку.</p>
            <form id="delete-account-form" action="/api/v1/users/me/delete-form" method="post" class="settings-delete-form">
                <div class="settings-form-group">
                    <label for="delete-password">Подтвердите паролем</label>
                    <input type="password" id="delete-password" name="password" placeholder="Ваш пароль" required>
                </div>
                <button type="submit" class="btn-outline settings-delete-btn" id="delete-account-btn">
                    <span class="settings-icon-sm">{ICON_TRASH}</span>
                    Удалить аккаунт
                </button>
            </form>
        </div>

    </div>
    """

    # HTML
    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Мой профиль — руми</title>
    {get_base_styles()}
</head>
<body>
    {render_header("profile")}
    {render_sidebar("profile", user)}

    <main class="profile-main">
        <div class="profile-container">

            <!-- Верхний блок (баннер) -->
            <div class="profile-banner">
                <div class="profile-avatar-wrapper">
                    <div class="profile-avatar" id="profile-avatar-container">
                        {f'<img src="{avatar_url}" alt="{name}">' if avatar_url else f'<span class="profile-avatar-letter">{avatar_letter}</span>'}
                        <button class="profile-avatar-edit" id="profile-avatar-edit" title="Изменить аватар">
                            {ICON_CAMERA}
                        </button>
                        <input type="file" id="profile-avatar-input" accept="image/*" style="display:none">
                    </div>
                </div>
                <button class="profile-edit-toggle" id="profile-edit-toggle">
                    {ICON_EDIT} Редактировать
                </button>
            </div>

            <!-- Информация (белый блок) -->
            <div class="profile-view" id="profile-view">
                <div class="profile-name-wrapper">
                    <h1 class="profile-name">{name}</h1>
                    <span class="profile-role-badge">{role_display}</span>
                </div>
                <div class="profile-meta">
                    <span class="profile-meta-item">
                        {ICON_PHONE} {phone}
                    </span>
                    {f'<span class="profile-meta-item">{ICON_MAIL} {email}</span>' if email else ''}
                    <span class="profile-meta-item">
                        {ICON_MAP_PIN_SMALL} {city}
                    </span>
                    {f'<span class="profile-meta-item">{ICON_CALENDAR_SMALL} С {member_since}</span>' if member_since else ''}
                </div>
                {error_message}
                {success_message}
            </div>

            <!-- Режим редактирования -->
            <div class="profile-edit" id="profile-edit" style="display:none;">
                <div class="profile-edit-header">
                    <h2>Редактирование профиля</h2>
                    <div class="profile-edit-actions">
                        <button class="profile-btn-cancel" id="profile-edit-cancel">Отмена</button>
                        <button class="profile-btn-primary" id="profile-edit-save">Сохранить</button>
                    </div>
                </div>
                <form id="profile-edit-form" action="/api/v1/users/me/update-form" method="post">
                    <div class="profile-form-group">
                        <label for="profile-edit-name">Имя *</label>
                        <input type="text" id="profile-edit-name" name="full_name" value="{name}" required>
                    </div>
                    {f'''
                    <div class="profile-form-group">
                        <label for="profile-edit-bio">О себе</label>
                        <textarea id="profile-edit-bio" name="portfolio_desc" rows="4" placeholder="Расскажите о себе...">{getattr(user, 'portfolio_desc', '')}</textarea>
                    </div>
                    ''' if role in ['model', 'master'] else ''}
                    <button type="submit" style="display:none;">Сохранить</button>
                </form>
                <div class="profile-edit-note">
                    <p class="text-muted">Телефон, email и город можно изменить ниже, в разделе «Смена данных».</p>
                </div>
            </div>

            <!-- Ролевой блок -->
            {role_block}

            <!-- Статус модели (аддитивный, независим от role_block) -->
            {model_block}

            <!-- Блоки настроек -->
            {settings_blocks}

        </div>
        {render_footer(user)}
    </main>
</body>
</html>"""
    return html


def _render_guest_page() -> str:
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Мой профиль — руми</title>
    {get_base_styles()}
</head>
<body>
    {render_header("profile")}
    {render_sidebar("profile", None)}
    <main class="profile-main">
        <div class="profile-container">
            <div class="profile-guest-card">
                <h2>{ICON_USER} Войдите в аккаунт</h2>
                <p>Чтобы просматривать и редактировать профиль, войдите или зарегистрируйтесь</p>
                <div class="profile-guest-actions">
                    <a href="/login" class="profile-btn-primary">Войти</a>
                    <a href="/register" class="profile-btn-outline">Зарегистрироваться</a>
                </div>
            </div>
        </div>
        {render_footer(None)}
    </main>
</body>
</html>"""