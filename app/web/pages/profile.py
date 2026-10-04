# app/web/pages/profile.py
"""«Мой профиль» — кто я, как со мной связаться, на что я согласился, как уйти.

Страница разложена по смыслу, а не одной простынёй: прежний порядок был
«баннер → роль → тема → уведомления → аккордеон смены данных → удаление»,
и человек, искавший, куда приходят напоминания, пролистывал мимо темы и
попадал в блок, где рядом с выбором канала лежала смена пароля.

Порядок теперь такой:
  1. **Кто я** — имя, роль, телефон, почта, город, аватар.
  2. **Как со мной связаться** — канал уведомлений: что подключено, куда идут
     сообщения, что сломалось.
  3. **Смена данных** — телефон, город, почта, пароль.
  4. **Оформление** — тема.
  5. **Согласия и документы** — редакция, тексты, рекламная рассылка.
  6. **Опасная зона** — удаление аккаунта. Не спрятано и не свёрнуто: право
     уйти обязано быть достижимо (152-ФЗ, ст. 9 ч. 2 — согласие отзывается).

Ни одна форма и ни один эндпоинт при переделке не исчезли; список — в
docs/decisions/0011.

Аккордеон переехал с <button> плюс класс из JS на <details> (ui.disclosure):
без скрипта прежние блоки смены телефона и пароля не раскрывались вовсе.

ВАЖНО: ``settings`` импортируется ВНУТРИ функций, а не на уровне модуля.
``app.core.config`` перезагружается (``importlib.reload``) — так устроены
guard'ы конфига и их тесты, — и после перезагрузки в модуле лежит НОВЫЙ объект
настроек. Модуль, сделавший ``from app.core.config import settings`` при
импорте, навсегда остаётся со старым: кнопка «Переподключить» тогда теряет
адрес бота и исчезает. Проверено поломкой — см. test_profile_survives_config_reload.
"""
from app.services import ad_consent
from app.web.cities import city_options_html
from app.web.components import ui
from app.web.components.escaping import e
from app.web.components.footer import render_footer
from app.web.components.header import render_header
from app.web.components.icons import (
    ICON_CAMERA,
    ICON_EDIT,
    ICON_LOCK_FILLED,
    ICON_MAIL_FILLED,
    ICON_MAP_PIN,
    ICON_MAP_PIN_FILLED,
    ICON_MOON,
    ICON_PHONE,
    ICON_PHONE_FILLED,
    ICON_STAR_FILLED,
    ICON_SUN,
    ICON_TRASH,
    ICON_USER,
    ICON_USERS,
)
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.pages.legal import DOCUMENTS, LEGAL_VERSION_HUMAN

# ВК показывает кнопку «Начать» только в ПУСТОМ диалоге. Кто уже писал
# сообществу, её не увидит — и не поймёт, что делать (так и случилось на
# стейдже 16.09). Метку привязки ВК передаёт с любым первым сообщением.
VK_START_HINT = (
    "Откроется страница привязки: кнопка в диалог с сообществом и короткий код "
    "на случай, если кнопки «Начать» в диалоге нет."
)

#: Документы, которые касаются клиента. Лицензионный договор и оферта для
#: салонов здесь не нужны — они про бизнесовую сторону, и ссылка на них из
#: клиентского профиля сбивала бы с толку. Полный список всегда на /legal.
_CLIENT_DOCS = ("terms", "privacy", "consent", "offer", "cookies")


def _vk_connect_button(label: str, kind: str = "secondary") -> str:
    """Кнопка привязки ВК ведёт на отдельную страницу /connect/vk: там один
    экран с кнопкой и кодом. Раньше форма сразу уводила во ВКонтакте, и если
    кнопки «Начать» в диалоге не было, человек оставался без подсказки."""
    from app.core.config import settings

    if not settings.vk_bot_address:
        return ""
    return ui.button(label, kind=kind, href="/connect/vk", small=True)


def _channels_overview(user, available) -> str:
    """Список каналов связи: что подключено и что с этим можно сделать.

    Раньше управление было размазано — телефон менялся в одном месте, почта
    другой формой, мессенджеры подключались только через /start в боте, а
    отвязать нельзя было вовсе. Здесь всё состояние видно сразу.

    Состояние названо СЛОВОМ, а не цветом: прежняя версия красила значение
    инлайновым style="color:#22c55e", и человек с выключенными цветами или
    дальтоник не отличал «подключён» от «не доставляется». Теперь это
    ui.status с тем же текстом.

    Строка списка — ``(название, значение, плашка-состояние, действия)``.
    ЗНАЧЕНИЕ приходит СЫРЫМ и экранируется здесь, в одном месте: имя ВК
    приходит из профиля человека и однажды уже было вектором (`vk_name` может
    содержать разметку). Плашка и действия — готовая разметка от ui.
    """
    from app.models.models import NotifyChannel
    from app.services.notify_channel import is_broken

    # settings — локально: конфиг перезагружается, см. docstring модуля.
    from app.core.config import settings

    rows = []
    rows.append(("Телефон", getattr(user, "phone", "") or "—",
                 ui.status("подтверждён", "success"), ""))

    def _messenger_row(channel, title, username, url_tpl):
        connected = channel in available
        disconnect = (
            '<form method="post" action="/api/v1/users/me/disconnect-channel" '
            'class="channel-form">'
            f'<input type="hidden" name="channel" value="{channel.value}">'
            + ui.button("Отвязать", kind="secondary", type_="submit", small=True)
            + "</form>"
        )
        if connected:
            if is_broken(user, channel):
                reconnect = ui.button(
                    "Переподключить", kind="secondary", small=True,
                    href=url_tpl.format(username),
                ) if username else ""
                return (title, "", ui.status("не доставляется", "danger"),
                        reconnect + disconnect)
            return (title, "", ui.status("подключён", "success"), disconnect)
        link = ui.button("Подключить", kind="secondary", small=True,
                         href=url_tpl.format(username)) if username else ""
        return (title, "", ui.status("не подключён", "neutral"), link)

    rows.append(_messenger_row(NotifyChannel.TG, "Telegram",
                               settings.TG_BOT_USERNAME, "https://t.me/{}"))
    rows.append(_messenger_row(NotifyChannel.MAX, "MAX",
                               settings.MAX_BOT_USERNAME, "https://max.ru/{}"))
    rows.append(_vk_row(user, available))
    rows = [row for row in rows if row is not None]

    email = (getattr(user, "email", "") or "").strip()
    rows.append(("Почта", email, ui.status("указана", "success")
                 if email else ui.status("не указана", "neutral"), ""))

    vk_hint = ""
    if settings.vk_bot_address and (
        NotifyChannel.VK not in available or is_broken(user, NotifyChannel.VK)
    ):
        vk_hint = f'<p class="r-field__hint">ВКонтакте: {e(VK_START_HINT)}</p>'

    items = ""
    for title, value, state, action in rows:
        items += (
            '<li class="channel-row">'
            '<div class="channel-row__id">'
            f'<span class="channel-row__name">{e(title)}</span>'
            + (f'<span class="channel-row__value">{e(value)}</span>' if value else "")
            + f'<span class="channel-row__state">{state}</span>'
            "</div>"
            f'<div class="channel-row__action">{action}</div>'
            "</li>"
        )
    return (
        f'<ul class="channel-list">{items}</ul>'
        '<p class="r-field__hint">Телефон и почта меняются ниже, в разделе '
        '«Смена данных».</p>'
        f"{vk_hint}"
    )


def _vk_row(user, available):
    """Строка ВКонтакте. Показываем ИМЯ привязанного аккаунта: если ссылку
    привязки успел открыть кто-то другой, человек увидит чужое имя и отвяжет."""
    from app.models.models import NotifyChannel
    from app.services import vk_api
    from app.services.notify_channel import is_broken

    # settings — локально: конфиг перезагружается, см. docstring модуля.
    from app.core.config import settings

    if not settings.vk_bot_address:
        return None
    disconnect = (
        '<form method="post" action="/api/v1/users/me/disconnect-channel" '
        'class="channel-form">'
        '<input type="hidden" name="channel" value="vk">'
        + ui.button("Отвязать", kind="secondary", type_="submit", small=True)
        + "</form>"
    )
    if NotifyChannel.VK in available:
        who = getattr(user, "vk_name", None) or ""
        if is_broken(user, NotifyChannel.VK):
            reconnect = ui.button("Переподключить", kind="secondary", small=True,
                                  href=vk_api.vk_me_url())
            return ("ВКонтакте", who, ui.status("не доставляется", "danger"),
                    reconnect + disconnect)
        return ("ВКонтакте", who, ui.status("подключён", "success"), disconnect)
    if getattr(user, "vk_user_id", None):
        # Вошёл через VK ID: бот узнает его сам, достаточно написать сообществу.
        return ("ВКонтакте", "напишите сообществу, и бот вас узнает",
                ui.status("не подключён", "neutral"),
                ui.button("Подключить", kind="secondary", small=True,
                          href=vk_api.vk_me_url()))
    return ("ВКонтакте", "", ui.status("не подключён", "neutral"),
            _vk_connect_button("Подключить"))


def _broken_banner(user, broken, channel) -> str:
    """Плашка «мессенджер перестал принимать сообщения».

    Без неё человек не узнал бы, что напоминания перестали приходить туда, где
    он их ждёт. Говорим, куда они идут сейчас и как вернуть: достаточно открыть
    бота и нажать «Начать» — привязка сохранилась.
    """
    from app.models.models import NotifyChannel
    from app.services.notify_channel import CHANNEL_LABELS

    # settings — локально: конфиг перезагружается, см. docstring модуля.
    from app.core.config import settings

    if not broken:
        return ""
    links = {
        NotifyChannel.TG: ("https://t.me/{}", settings.TG_BOT_USERNAME),
        NotifyChannel.MAX: ("https://max.ru/{}", settings.MAX_BOT_USERNAME),
        NotifyChannel.VK: ("https://vk.me/{}", settings.vk_bot_address),
    }
    names = " и ".join(CHANNEL_LABELS[c] for c in broken)
    buttons = "".join(
        ui.button(f"Открыть бота: {CHANNEL_LABELS[c]}", kind="secondary", small=True,
                  href=tpl.format(username))
        for c in broken
        for tpl, username in [links[c]] if username
    )
    if channel == NotifyChannel.NONE:
        now = "Сейчас уведомления не приходят никуда."
    else:
        # Название канала жирным: это единственная строка, из которой человек
        # узнаёт, куда уходят уведомления вместо сломанного мессенджера.
        now = (f"Пока уведомления приходят: "
               f"<strong>{e(CHANNEL_LABELS[channel])}</strong>.")
    return (
        '<div class="r-notice r-notice--danger channel-broken" role="alert">'
        f"<strong>{e(names)} не принимает наши сообщения.</strong> "
        f"Похоже, бот заблокирован или чат с ним удалён. {now}"
        '<span class="channel-broken__how">Чтобы вернуть: откройте бота и нажмите '
        "«Начать» (или «Перезапустить»). Заново привязывать ничего не нужно.</span>"
        f'<span class="channel-broken__actions">{buttons}</span>'
        "</div>"
    )


def _notify_channel_block(user) -> str:
    """Реальное управление каналом уведомлений.

    Раньше здесь стояла заглушка (чекбоксы и селект email/vk/telegram, ни к
    чему не подключённые). Теперь показываем фактический канал, даём
    переключиться на любой ПОДКЛЮЧЁННЫЙ и мягко зовём подключить, если
    доставлять некуда — блокировать ничего не нужно.
    """
    from app.models.models import NotifyChannel
    from app.services import vk_api
    from app.services.notify_channel import CHANNEL_LABELS, broken_channels, resolve

    # settings — локально: конфиг перезагружается, см. docstring модуля.
    from app.core.config import settings

    if user is None:
        return ""

    channel, _address = resolve(user)
    available = []
    if getattr(user, "tg_chat_id", None):
        available.append(NotifyChannel.TG)
    if getattr(user, "max_chat_id", None):
        available.append(NotifyChannel.MAX)
    if getattr(user, "vk_peer_id", None):
        available.append(NotifyChannel.VK)
    if (getattr(user, "email", "") or "").strip():
        available.append(NotifyChannel.EMAIL)

    if not available:
        # Канала нет — мягкий промпт, без запретов.
        links = []
        if settings.TG_BOT_USERNAME:
            links.append(ui.button(
                "Подключить Telegram", kind="secondary", small=True,
                href=f"https://t.me/{settings.TG_BOT_USERNAME}"))
        if settings.MAX_BOT_USERNAME:
            links.append(ui.button(
                "Подключить MAX", kind="secondary", small=True,
                href=f"https://max.ru/{settings.MAX_BOT_USERNAME}"))
        if settings.vk_bot_address:
            links.append(
                ui.button("Подключить ВКонтакте", kind="secondary", small=True,
                          href=vk_api.vk_me_url())
                if getattr(user, "vk_user_id", None)
                else _vk_connect_button("Подключить ВКонтакте")
            )
        return (
            '<p class="r-text">Канал уведомлений не подключён — напоминания о '
            "записях и важные сообщения приходить не будут. Подключите мессенджер "
            "или укажите почту в разделе «Смена данных».</p>"
            f'<div class="channel-actions">{"".join(links)}</div>'
            + (f'<p class="r-field__hint">ВКонтакте: {e(VK_START_HINT)}</p>'
               if settings.vk_bot_address else "")
        )

    options = "".join(
        f'<option value="{c.value}"{" selected" if c == channel else ""}>'
        f"{CHANNEL_LABELS[c]}</option>"
        for c in available
    )
    missing = []
    if NotifyChannel.TG not in available and settings.TG_BOT_USERNAME:
        missing.append(
            f'<a href="https://t.me/{settings.TG_BOT_USERNAME}" target="_blank" '
            'rel="noopener">Telegram</a>'
        )
    if NotifyChannel.MAX not in available and settings.MAX_BOT_USERNAME:
        missing.append(
            f'<a href="https://max.ru/{settings.MAX_BOT_USERNAME}" target="_blank" '
            'rel="noopener">MAX</a>'
        )
    if NotifyChannel.VK not in available and settings.vk_bot_address:
        missing.append('<a href="/connect/vk">ВКонтакте</a>')
    missing_hint = (
        f'<p class="r-field__hint">Можно подключить ещё: {", ".join(missing)}.</p>'
        if missing else ""
    )

    return (
        _broken_banner(user, broken_channels(user), channel)
        + _channels_overview(user, available)
        + '<form method="post" action="/api/v1/users/me/notify-channel" '
          'class="channel-pick">'
          '<label class="r-field__label" for="notify-method">Куда присылать '
          "уведомления</label>"
          '<div class="channel-pick__row">'
          '<select name="channel" id="notify-method" class="r-input custom-select">'
        + options
        + "</select>"
        + ui.button("Сохранить", type_="submit", small=True)
        + "</div></form>"
        + f'<p class="r-field__hint">Сейчас уведомления приходят: '
          f"<strong>{CHANNEL_LABELS[channel]}</strong>.</p>"
        + missing_hint
    )


def _consents_block(user) -> str:
    """Согласия и документы. ЧИТАЕТ состояние, ничего не меняет.

    Почему только чтение. Согласие на обработку персональных данных даётся при
    регистрации и при записи (``components/consent.py``), в журнал уходит
    вместе с редакцией (``UserConsent.version``); отозвать его — это и есть
    удаление аккаунта, которое стоит ниже отдельным разделом. Рекламную
    рассылку включает ТОЛЬКО ``services/ad_consent.grant`` — он пишет
    доказательство в журнал, и переключателя для неё на вебе нет: он живёт в
    «Моих уведомлениях» в боте. Завести его здесь — отдельная работа, а не
    переделка вида, поэтому раздел говорит правду и показывает, где рычаг.

    До этого захода на странице профиля не было НИ слова ни о согласиях, ни о
    документах: единственная ссылка на /legal стояла в подвале.
    """
    docs = "".join(
        f'<li><a href="/{DOCUMENTS[slug]["slug"]}">{e(DOCUMENTS[slug]["title"])}</a></li>'
        for slug in _CLIENT_DOCS if slug in DOCUMENTS
    )
    promo_on = ad_consent.is_consented(user)
    promo_state = (ui.status("включена", "success") if promo_on
                   else ui.status("выключена", "neutral"))
    promo_how = (
        "Отключить можно там же, где включали — в разделе «Мои уведомления» "
        "в Telegram, MAX или ВКонтакте."
        if promo_on else
        "Мы не присылаем её без вашего согласия. Включить — в разделе «Мои "
        "уведомления» в Telegram, MAX или ВКонтакте."
    )
    return (
        '<p class="r-text">Пользуясь Руми, вы согласились с документами ниже. '
        f"Действующая редакция — от {e(LEGAL_VERSION_HUMAN)}; с какой именно "
        "редакцией согласились вы, записано в нашем журнале согласий.</p>"
        f'<ul class="profile-docs">{docs}</ul>'
        '<p class="r-seclink-wrap"><a class="r-seclink" href="/legal">'
        "Все документы сервиса</a></p>"
        '<div class="profile-promo">'
        f'<p class="r-field__label">Рассылка об акциях и конкурсах {promo_state}</p>'
        f'<p class="r-field__hint">{e(promo_how)} Уведомления о ваших записях '
        "это не затрагивает.</p>"
        "</div>"
    )


def _role_blocks(user, master_profile, salon) -> str:
    """Что ещё есть у этого человека: кабинет мастера, салон, статус модели.

    Блоки мастера и салона приходят параметрами и на /profile пока не
    заполняются (вызов в views.py передаёт только пользователя) — разметка
    сохранена дословно, чтобы они заработали, как только их начнут передавать.
    """
    role = user.role.value if user.role else "client"
    blocks = []

    if role == "master" and master_profile:
        blocks.append(ui.card(
            ui.facts((
                ("Специализация", e(master_profile.specialization or "—")),
                ("Опыт", f"{master_profile.experience_years or 0} лет"),
                ("Рейтинг", f"{ICON_STAR_FILLED} {master_profile.rating or 0}"),
            ))
            + (f'<p class="r-text">{e(master_profile.bio)}</p>'
               if master_profile.bio else "")
            + '<div class="profile-links">'
            + ui.button("Моё портфолио", kind="secondary", small=True,
                        href=f"/masters/{master_profile.id}")
            + ui.button("Моё расписание", kind="secondary", small=True,
                        href="/master/schedule")
            + "</div>",
            title="Профессиональная информация",
        ))

    elif role == "business" and salon:
        blocks.append(ui.card(
            ui.facts((
                ("Салон", e(salon.name or "—")),
                ("Адрес", f"{ICON_MAP_PIN} {e(salon.address or '—')}"),
                ("Телефон", f"{ICON_PHONE} {e(salon.phone or '—')}"),
                ("Оценка", f"{ICON_STAR_FILLED} {salon.rating or 0} "
                           f"({salon.reviews_count or 0} отзывов)"),
                ("Мастера", f"{ICON_USERS} {getattr(salon, 'masters_count', 0)}"),
            ))
            + '<div class="profile-links">'
            + ui.button("Панель управления", kind="secondary", small=True,
                        href="/business/dashboard")
            + "</div>",
            title="Мой салон",
        ))

    # «Модель» — аддитивный статус поверх обычной роли (не сама role), поэтому
    # блок считается независимо от роли и может показываться вместе с ней.
    if bool(getattr(user, "is_model", False)):
        moderation = getattr(user, "model_moderation_status", None)
        value = moderation.value if moderation else "pending"
        state = {
            "pending": ui.status("На модерации", "warning"),
            "approved": ui.status("Одобрена", "success"),
            "rejected": ui.status("Отклонена", "danger"),
        }.get(value, "")
        reason = getattr(user, "model_rejection_reason", "") or ""
        photo = getattr(user, "model_photo_url", None) or ""
        bio = getattr(user, "model_bio", "") or ""
        blocks.append(ui.card(
            f'<p class="profile-model__state">{state}</p>'
            + (f'<p class="r-field__hint">Причина: {e(reason)}</p>'
               if value == "rejected" and reason else "")
            + (f'<p class="profile-model__photo">{ui.mark("", image=photo, alt="Фото анкеты")}</p>'
               if photo else "")
            + (f'<p class="r-text">{e(bio)}</p>' if bio else "")
            + '<div class="profile-links">'
            + ui.button("Лента и мои мэтчи", kind="secondary", small=True,
                        href="/model/dashboard")
            + ui.button("Редактировать анкету", kind="secondary", small=True,
                        href="/model/join")
            + "</div>",
            title="Статус «Модель»",
        ))
    else:
        blocks.append(ui.card(
            '<p class="r-text">Позвольте мастерам отработать на вас технику за '
            "скидку или бесплатно — заведите анкету и смотрите, кто ищет "
            "модель.</p>"
            '<div class="profile-links">'
            + ui.button("Стать моделью", kind="secondary", small=True,
                        href="/model/join")
            + "</div>",
            title="Стать моделью",
        ))

    if not blocks:
        return ""
    return f'<div class="profile-roles">{"".join(blocks)}</div>'


def _phone_form(phone: str) -> str:
    """Смена телефона — только с подтверждением владения новым номером через
    мессенджер (телефон = логин-идентификатор). Механика та же, что при
    регистрации: кнопка → /register/{tg,max}-start → бот подтверждает →
    request_id → сабмит.

    Подтвердить новый номер можно любым рабочим мессенджером — раньше был
    зашит только Telegram, и владельцы MAX менять телефон не могли вовсе.
    """
    # settings — локально: конфиг перезагружается, см. docstring модуля.
    from app.core.config import settings

    verify_buttons = []
    channels = []
    if settings.TG_VERIFY_ENABLED:
        channels.append("Telegram")
        verify_buttons.append(ui.button(
            "Подтвердить в Telegram", kind="secondary", small=True,
            element_id="phone-verify-btn", classes="phone-verify-btn",
            data={"start-url": "/api/v1/auth/register/tg-start",
                  "channel": "Telegram"},
        ))
    if settings.MAX_VERIFY_ENABLED:
        channels.append("MAX")
        verify_buttons.append(ui.button(
            "Подтвердить в MAX", kind="secondary", small=True,
            classes="phone-verify-btn",
            data={"start-url": "/api/v1/auth/register/max-start",
                  "channel": "MAX"},
        ))

    if not verify_buttons:
        return '<p class="r-field__hint">Смена телефона временно недоступна.</p>'

    return (
        '<form id="phone-change-form" action="/api/v1/users/me/phone-form" '
        'method="post">'
        + ui.field("Новый телефон", name="phone", element_id="settings-phone",
                   type_="tel", value=phone, placeholder="+7XXXXXXXXXX",
                   required=True, autocomplete="tel",
                   # Подсказка идёт ЗА полем, а не между кнопками: объяснение,
                   # что делать, попадалось на глаза уже после первого
                   # действия. Так же устроен блок смены email.
                   hint=f"Введите новый номер и подтвердите владение им в "
                        f"{' или '.join(channels)}.")
        + '<input type="hidden" id="phone-request-id" name="request_id" value="">'
        '<p class="r-field__hint" id="phone-verify-hint"></p>'
        f'<div class="profile-links">{"".join(verify_buttons)}</div>'
        + ui.button("Сохранить", type_="submit", element_id="phone-save-btn",
                    disabled=True)
        + "</form>"
    )


def _email_form(email: str) -> str:
    """Смена почты — с подтверждением кодом, отправленным на НОВЫЙ адрес."""
    return (
        '<form id="email-change-form" action="/api/v1/users/me/email-form" '
        'method="post">'
        + ui.field("Новый email", name="email", element_id="settings-email",
                   type_="email", value=email, placeholder="example@mail.ru",
                   required=True, autocomplete="email",
                   hint="Введите новый email и получите на него код "
                        "подтверждения.")
        + '<input type="hidden" id="email-request-id" name="request_id" value="">'
        '<p class="r-field__hint" id="email-verify-hint"></p>'
        + '<div class="profile-links">'
        + ui.button("Отправить код", kind="secondary", small=True,
                    element_id="email-send-code-btn")
        + "</div>"
        '<div id="email-code-group" style="display:none">'
        + ui.field("Код из письма", name="code",
                   element_id="settings-email-code", inputmode="numeric",
                   autocomplete="one-time-code", placeholder="0000")
        + "</div>"
        + ui.button("Подтвердить и сохранить", type_="submit",
                    element_id="email-save-btn", disabled=True)
        + "</form>"
    )


def render_profile_page(user=None, master_profile=None, salon=None, stats=None,
                        error=None, success=None) -> str:
    """Страница профиля.

    ``error``/``success`` — коды из адреса. Все формы профиля отвечают
    редиректом на ``/profile?success=…`` либо ``/profile?error=…``, но до этого
    захода страница эти параметры не читала вовсе: человек менял пароль и не
    видел ни «готово», ни «неверный текущий пароль». Коды и тексты здесь те
    же, что были написаны раньше, — теперь они доезжают до экрана.
    """
    if not user:
        return _render_guest_page()

    error_messages = {
        "email_taken": "Этот email уже используется другим пользователем",
        "wrong_password": "Неверный текущий пароль",
        "password_mismatch": "Новые пароли не совпадают",
        "password_too_short": "Пароль должен быть не менее 8 символов",
        "phone_exists": "Пользователь с таким телефоном уже зарегистрирован",
        "bad_phone": "Некорректный номер телефона",
        "bad_city": "Выберите город из списка подсказок",
        "phone_not_verified": "Номер не подтверждён — подтвердите его в мессенджере",
        "email_not_verified": "Код неверный или истёк — запросите новый",
        "otp_unavailable": "Сервис подтверждения временно недоступен, попробуйте позже",
        "update_failed": "Не удалось обновить профиль",
        "notify_channel_invalid": "Неизвестный канал уведомлений",
        "vk_unavailable": "Подключение ВКонтакте сейчас недоступно",
        "notify_channel_unavailable": "Этот канал не подключён — сначала привяжите "
                                      "бота или укажите почту",
        "notify_channel_last": "Это единственный канал связи — сначала подключите "
                               "другой, иначе уведомления перестанут приходить",
    }
    success_messages = {
        "updated": "Профиль обновлён",
        "password_updated": "Пароль изменён",
        "email_updated": "Email обновлён",
        "city_updated": "Город обновлён",
        "phone_updated": "Телефон обновлён",
        "avatar_updated": "Аватар обновлён",
        "notify_channel_updated": "Канал уведомлений обновлён",
        "notify_channel_disconnected": "Мессенджер отвязан",
    }

    notice_html = ""
    if error:
        notice_html = ui.notice(
            error_messages.get(error, "Произошла ошибка"), tone="danger",
            element_id="profile-error")
    elif success:
        notice_html = ui.notice(
            success_messages.get(success, "Готово"), tone="success",
            element_id="profile-success")

    name = user.full_name or "Пользователь"
    phone = user.phone or "+7"
    email = user.email or ""
    city = getattr(user, "city", "") or ""
    avatar_url = user.avatar_url or ""
    role = user.role.value if user.role else "client"
    created_at = getattr(user, "created_at", None)
    member_since = created_at.strftime("%d.%m.%Y") if created_at else ""

    role_display = {
        "client": "Клиент",
        "model": "Модель",
        "master": "Мастер",
        "business": "Владелец салона",
        "admin": "Администратор",
    }.get(role, role.capitalize())

    # ---------- 1. Кто я ----------
    who = ui.card(
        '<div class="profile-id">'
        '<div class="profile-avatar" id="profile-avatar-container">'
        + (f'<img src="{e(avatar_url)}" alt="{e(name)}">' if avatar_url
           else f'<span class="profile-avatar-letter" aria-hidden="true">'
                f'{e(name[0].upper())}</span>')
        + '<button class="profile-avatar-edit" id="profile-avatar-edit" '
          'type="button" aria-label="Изменить фото">'
        + ICON_CAMERA
        + "</button>"
          '<input type="file" id="profile-avatar-input" accept="image/*" '
          'hidden>'
          "</div>"
        '<div class="profile-id__text">'
        f'<h2 class="r-title profile-name">{e(name)}</h2>'
        f'{ui.status(role_display, "neutral")}'
        "</div>"
        + ui.button("Изменить имя", kind="secondary", small=True,
                    element_id="profile-edit-toggle", icon=ICON_EDIT)
        + "</div>"
        + ui.facts((
            ("Телефон", e(phone)),
            ("Почта", e(email) if email else "не указана"),
            ("Город", e(city) if city else "не указан"),
            ("С нами с", e(member_since)),
        ))
        # Форма имени свёрнута, а не отдельным «режимом редактирования» на всю
        # карточку: прежняя версия подменяла блок целиком, и человек терял из
        # вида телефон и город ровно тогда, когда правил имя.
        + '<form id="profile-edit-form" action="/api/v1/users/me/update-form" '
          'method="post" class="profile-edit-form" hidden>'
        + ui.field("Имя", name="full_name", element_id="profile-edit-name",
                   value=name, required=True, autocomplete="name")
        + (
            '<div class="r-field">'
            '<label class="r-field__label" for="profile-edit-bio">О себе</label>'
            '<textarea class="r-input" id="profile-edit-bio" name="portfolio_desc" '
            'rows="4" placeholder="Расскажите о себе">'
            f'{e(getattr(user, "portfolio_desc", "") or "")}</textarea></div>'
            if role in ("model", "master") else ""
        )
        + '<div class="profile-links">'
        + ui.button("Сохранить", type_="submit", small=True)
        + ui.button("Отмена", kind="secondary", small=True,
                    element_id="profile-edit-cancel")
        + "</div></form>"
        '<p class="r-field__hint">Телефон, почту и город можно изменить ниже, '
        "в разделе «Смена данных».</p>",
        title="Кто я",
    )

    # ---------- 3. Смена данных ----------
    change = ui.card(
        ui.disclosure("Сменить телефон", _phone_form(phone),
                      element_id="accordion-phone", icon=ICON_PHONE_FILLED)
        + ui.disclosure(
            "Сменить город",
            '<form action="/api/v1/users/me/city-form" method="post">'
            '<div class="r-field">'
            '<label class="r-field__label" for="settings-city">Новый город</label>'
            '<select id="settings-city" name="city" '
            'class="r-input custom-select city-select">'
            '<option value="">Не указан</option>'
            + city_options_html(city)
            + "</select></div>"
            + ui.button("Сохранить", type_="submit")
            + "</form>",
            element_id="accordion-city", icon=ICON_MAP_PIN_FILLED)
        + ui.disclosure("Сменить email", _email_form(email),
                        element_id="accordion-email", icon=ICON_MAIL_FILLED)
        + ui.disclosure(
            "Сменить пароль",
            '<form action="/api/v1/users/me/password-form" method="post">'
            + ui.field("Текущий пароль", name="current_password",
                       element_id="settings-current-password", type_="password",
                       required=True, autocomplete="current-password")
            + ui.field("Новый пароль", name="new_password",
                       element_id="settings-new-password", type_="password",
                       required=True, autocomplete="new-password")
            + ui.field("Подтвердите пароль", name="confirm_password",
                       element_id="settings-confirm-password", type_="password",
                       required=True, autocomplete="new-password")
            + ui.button("Сохранить", type_="submit")
            + "</form>",
            element_id="accordion-password", icon=ICON_LOCK_FILLED)
        + "",
        title="Смена данных",
        text="Телефон и почта подтверждаются — это ваш вход в сервис.",
    )

    # ---------- 6. Опасная зона ----------
    danger = ui.card(
        '<p class="r-text">Аккаунт будет деактивирован: вы выйдете из системы и '
        "не сможете войти. Данные сохраняются — для восстановления или полного "
        "удаления обратитесь в поддержку.</p>"
        '<form id="delete-account-form" action="/api/v1/users/me/delete-form" '
        'method="post">'
        + ui.field("Подтвердите паролем", name="password",
                   element_id="delete-password", type_="password",
                   placeholder="Ваш пароль", required=True,
                   autocomplete="current-password")
        + ui.button("Удалить аккаунт", kind="danger", icon=ICON_TRASH,
                    type_="submit", element_id="delete-account-btn")
        + "</form>",
        title="Удаление аккаунта",
        classes="r-card--danger",
    )

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <title>Мой профиль — руми</title>
    <meta name="robots" content="noindex, nofollow">
    {get_base_styles()}
</head>
<body class="page-body">
    {render_header("profile")}
    {render_sidebar("profile", user)}

    <main class="main-content cabinet-main profile-main">
        <div class="section-container">
            <header class="cabinet-head">
                <h1 class="r-display">Мой профиль</h1>
                <p class="r-text r-muted">Кто вы, как с вами связаться и что мы
                    о вас храним.</p>
            </header>
            {notice_html}

            <div class="profile-stack">
                {who}
                {_role_blocks(user, master_profile, salon)}

                {ui.card(_notify_channel_block(user),
                         title="Как со мной связаться",
                         text="Сюда приходят напоминания о записях и ответы "
                              "мастера.")}

                {change}

                {ui.card(
                    '<div class="theme-toggle" role="group" '
                    'aria-label="Оформление интерфейса">'
                    + ui.button("Светлая", kind="secondary", small=True,
                                icon=ICON_SUN, classes="theme-btn",
                                data={"theme": "light"})
                    + ui.button("Тёмная", kind="secondary", small=True,
                                icon=ICON_MOON, classes="theme-btn",
                                data={"theme": "dark"})
                    + '</div>'
                      '<p class="r-field__hint">Выбор сохраняется в этом '
                      'браузере.</p>',
                    title="Оформление")}

                {ui.card(_consents_block(user), title="Согласия и документы")}

                {danger}
            </div>
        </div>
        {render_footer(user)}
    </main>
</body>
</html>"""


def _render_guest_page() -> str:
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <title>Мой профиль — руми</title>
    <meta name="robots" content="noindex, nofollow">
    {get_base_styles()}
</head>
<body class="page-body">
    {render_header("profile")}
    {render_sidebar("profile", None)}
    <main class="main-content cabinet-main profile-main">
        <div class="section-container">
            <header class="cabinet-head">
                <h1 class="r-display">Мой профиль</h1>
            </header>
            {ui.card(
                f'<p class="r-text">{ICON_USER} Чтобы смотреть и менять профиль, '
                'войдите или зарегистрируйтесь.</p>'
                '<div class="profile-links">'
                + ui.button("Войти", href="/login")
                + ui.button("Зарегистрироваться", kind="secondary", href="/register")
                + '</div>',
                title="Войдите в аккаунт")}
        </div>
        {render_footer(None)}
    </main>
</body>
</html>"""
