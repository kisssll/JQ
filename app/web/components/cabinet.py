# app/web/components/cabinet.py
"""Оболочка личного кабинета по макету дизайнера (её Account, решение 0015, п. 3).

Слева липкая карточка (аватар, имя, телефон, разделы, «Выйти»), справа заголовок,
пилюля действия, числа и содержимое. «Мой профиль», «Мои записи» и «Избранное» —
разделы одного кабинета с общим левым столбцом. Логику страниц оболочка не
трогает: страница отдаёт готовый HTML содержимого.
"""
from app.web.components import ui
from app.web.components.escaping import e
from app.web.components.icons import ICON_LOGOUT

CABINET_SECTIONS = (
    ("profile", "/profile", "Мой профиль"),
    ("bookings", "/bookings", "Мои записи"),
    ("favorites", "/favorites", "Избранное"),
)


def _nav_link(href: str, label: str, on: bool) -> str:
    cur = ' aria-current="page"' if on else ""
    return f'<a href="{href}" class="acc-link{" on" if on else ""}"{cur}>{label}</a>'


def _stats(stats) -> str:
    # Числа показываем только настоящие: пустой список — блока нет вовсе.
    if not stats:
        return ""
    cells = "".join(f"<div><b>{e(str(v))}</b><span>{e(label)}</span></div>"
                    for v, label in stats)
    return f'<div class="acc-stats" data-count="{len(stats)}">{cells}</div>'


def render_cabinet(user, current: str, title: str, lead: str, content: str, *,
                   action: tuple[str, str] | None = None, stats=None,
                   badge: str | list[str] = "", extra_class: str = "") -> str:
    """``action`` — (подпись, адрес) пилюли справа от заголовка; ``stats`` —
    [(число, подпись)], только реальные; ``badge`` — подписи подписок, которые
    у человека есть по-настоящему (app/services/cabinet_badge.py), иначе пусто."""
    # Имя из пробелов — пустое имя (см. render_account_tag в шапке).
    full_name = (user.full_name or "").strip()
    name = full_name or user.phone or "Пользователь"
    phone = (f'<p class="acc-phone">{e(user.phone)}</p>'
             if user.phone and full_name else "")
    badges = [badge] if isinstance(badge, str) else list(badge or [])
    badge_html = "".join(f'<span class="acc-badge">{e(b)}</span>' for b in badges if b)
    nav = "".join(_nav_link(href, label, key == current)
                  for key, href, label in CABINET_SECTIONS)
    act = (ui.button(action[0], href=action[1]) if action else "")
    return f"""
        <div class="section-container">
            <div class="account {extra_class}">
                <aside class="acc-side" aria-label="Личный кабинет">
                    {ui.mark(name, image=getattr(user, "avatar_url", "") or "",
                             alt=name, size="xl")}
                    <h2 class="acc-name">{e(name)}</h2>
                    {phone}
                    {badge_html}
                    <nav class="acc-nav" aria-label="Разделы кабинета">{nav}</nav>
                    <a class="acc-logout" href="/logout">{ICON_LOGOUT} Выйти</a>
                </aside>
                <div class="acc-main">
                    <header class="acc-head">
                        <div>
                            <h1 class="r-display">{e(title)}</h1>
                            <p class="r-text r-muted">{lead}</p>
                        </div>
                        {act}
                    </header>
                    {_stats(stats)}
                    {content}
                </div>
            </div>
        </div>"""
