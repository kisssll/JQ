# app/web/components/header.py
from app.web.components.escaping import e
from app.web.components.icons import (
    ICON_BRIEFCASE,
    ICON_CALENDAR_DAYS_SIDEBAR,
    ICON_HEART,
    ICON_LOGOUT,
    ICON_MENU,
    ICON_MODEL,
    ICON_USER,
)

# Ровно шесть публичных пунктов — как NAV в макете дизайнера (решение 0015, п. 1).
# Ключ — то, что страницы передают как current_page.
PUBLIC_NAV = (
    ("home", "/", "Главная"),
    ("salons", "/salons", "Салоны"),
    ("business", "/business", "Для бизнеса"),
    ("model", "/model", "Стать моделью"),
    ("manifest", "/about", "Манифест"),
    ("tariffs", "/tariffs", "Тарифы"),
)


def _link(href: str, icon: str, label: str, extra: str = "") -> str:
    return f'<a class="acct-menu__link {extra}" href="{href}">{icon}{label}</a>'


def _nav_link(href: str, label: str, active: bool) -> str:
    cls = "header-link active" if active else "header-link"
    cur = ' aria-current="page"' if active else ""
    return f'<a class="{cls}" href="{href}"{cur}>{label}</a>'


def render_account_tag(user=None) -> str:
    """Качающаяся этикетка — вход в аккаунт и всё личное (решение 0015, п. 2).

    Это настоящая кнопка (aria-expanded), а не hover-меню: на телефоне hover
    залипает, а с клавиатуры до него не добраться. Обещаний («30 секунд · 4 клика»)
    на ней нет — ничем не подтверждены (ч. 7 ст. 5 закона «О рекламе»).
    """
    if user:
        name = user.full_name or user.phone or "Пользователь"
        label = e(name.split()[0])
        items = f'<div class="acct-menu__who">{e(name)}</div>'
        items += _link("/profile", ICON_USER, "Мой профиль")
        items += _link("/bookings", ICON_CALENDAR_DAYS_SIDEBAR, "Мои записи")
        items += _link("/favorites", ICON_HEART, "Избранное")

        role = getattr(getattr(user, "role", None), "value", None)
        panel = ""
        if (
            role in ("business", "master")
            or getattr(user, "has_salon_access", False)
            or getattr(user, "has_master_profile", False)
        ):
            panel += _link("/business/dashboard", ICON_BRIEFCASE, "Панель бизнеса")
        if getattr(user, "is_model", False):
            panel += _link("/model/dashboard", ICON_MODEL, "Кабинет модели")
        if role == "admin":
            panel += _link("/admin", ICON_USER, "Админка")
        if panel:
            items += '<div class="acct-menu__sep"></div>' + panel
        items += '<div class="acct-menu__sep"></div>'
        items += _link("/logout", ICON_LOGOUT, "Выйти", "acct-menu__link--out")
    else:
        label = "Войти"
        items = (
            _link("/login", ICON_USER, "Войти", "acct-menu__link--main")
            + _link("/register", ICON_USER, "Регистрация")
        )

    return f"""
    <div class="acct-tag" id="acct-tag">
        <button type="button" class="acct-tag__btn" id="acct-tag-btn"
                aria-expanded="false" aria-controls="acct-menu"
                aria-label="Аккаунт: {'меню' if user else 'вход и регистрация'}">
            <span class="acct-tag__string" aria-hidden="true"></span>
            <span class="acct-tag__card">
                <span class="acct-tag__hole" aria-hidden="true"></span>
                {ICON_USER}
                <span class="acct-tag__label">{label}</span>
            </span>
        </button>
        <nav class="acct-menu" id="acct-menu" aria-label="Аккаунт" hidden>
            {items}
        </nav>
    </div>
    """


def render_header(current_page: str = "home", user=None, panel: bool = False) -> str:
    """Закреплённая шапка: логотип, шесть публичных пунктов, этикетка-вход.

    Логотип — картинка, а не текст: начертание рукописное, системным шрифтом
    его не набрать. Размеры у <img> проставлены, чтобы шапка не дёргалась,
    пока файл грузится.

    panel=True — страницы бизнес-панели: там своя навигация, этикетки нет;
    справа остаются выходы на сайт, в профиль и из аккаунта.
    """
    logo = """
            <a href="/" id="header-logo" aria-label="Руми — на главную">
                <picture>
                    <source type="image/webp" srcset="/static/images/rumi-logo.webp">
                    <img src="/static/images/rumi-logo.png" alt="Руми"
                         width="480" height="312">
                </picture>
            </a>"""

    if panel:
        return f"""
    <header id="main-header">
        <div class="header-row">{logo}
            <nav class="header-panel" aria-label="Выходы из панели">
                <a class="header-link" href="/">На сайт</a>
                <a class="header-link" href="/profile">Профиль</a>
                <a class="header-link" href="/logout">Выйти</a>
            </nav>
        </div>
    </header>
    """

    links = "".join(
        _nav_link(href, label, key == current_page) for key, href, label in PUBLIC_NAV
    )
    return f"""
    <header id="main-header">
        <div class="header-row">{logo}
            <nav id="header-nav" aria-label="Разделы сайта">{links}</nav>
            <button type="button" id="header-burger" aria-label="Открыть меню"
                    aria-expanded="false" aria-controls="header-nav">
                {ICON_MENU}
            </button>
        </div>
    </header>
    {render_account_tag(user)}
    """
