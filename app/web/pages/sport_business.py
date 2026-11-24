import html

from app.models.sport import SportOrganization
from app.web.components.footer import render_footer
from app.web.components.header import render_header
from app.web.components.styles import get_base_styles
from app.web.pages.legal import LEGAL_VERSION


def render_sport_business_page(
    user=None,
    organizations: list[SportOrganization] | None = None,
    success: bool = False,
) -> str:
    organizations = organizations or []
    status_labels = {
        "pending": "На модерации",
        "approved": "Одобрен",
        "rejected": "Отклонён",
    }
    success_banner = ""
    if success:
        success_banner = """
        <div class="sport-business__success" style="background:var(--color-success-light, #e6f9ed);color:var(--color-success, #12803b);padding:1rem 1.25rem;border-radius:var(--radius-16, 16px);margin-bottom:2rem;font-size:0.95rem;line-height:1.5;">
            <strong>Заявка на подключение клуба принята!</strong><br>
            Клуб отправлен на модерацию. Вы уже можете перейти в управление залом для настройки расписания, тренеров и направлений.
        </div>"""

    cta_register = """
        <div style="margin: 1.5rem 0 2rem;">
            <a href="/sport/business/register-gym" class="btn-primary" style="display:inline-block;padding:0.75rem 1.5rem;text-decoration:none;border-radius:var(--radius-16, 16px);font-weight:600;">
                + Заполнить анкету и добавить клуб
            </a>
        </div>"""

    if user:
        applications = "".join(
            '<article class="sport-business__application">'
            f'<h3>{html.escape(item.name)}</h3>'
            f'<p>{html.escape(item.city)} · Статус: {html.escape(status_labels.get(item.moderation_status, item.moderation_status))}</p>'
            + (
                f'<p>{html.escape(item.rejection_reason)}</p>'
                if item.rejection_reason
                else ""
            )
            + f'<a href="/sport/{html.escape(item.slug, quote=True)}/admin">Перейти к управлению</a>'
            + "</article>"
            for item in organizations
        )
        form = """
        <form class="sport-business__form" method="post" action="/api/v1/sport/business/apply">
            <label>Название клуба<input name="name" required maxlength="160"></label>
            <label>Город<input name="city" required maxlength="100"></label>
            <label>Адрес основного зала<input name="address" required maxlength="300"></label>
            <label>Телефон для связи<input name="phone" required maxlength="24"></label>
            <label>Email<input name="email" type="email" maxlength="254"></label>
            <label>Коротко о клубе<textarea name="description" maxlength="4000"></textarea></label>
            <input type="hidden" name="consent_version" value="{version}">
            <label class="sport-business__check">
                <input type="checkbox" name="offer_accepted" value="1" required>
                Принимаю <a href="/sport/legal/license" target="_blank" rel="noopener noreferrer">условия для спортивных клубов</a>.
            </label>
            <label class="sport-business__check">
                <input type="checkbox" name="pd_consent" value="1" required>
                Согласен(на) на обработку персональных данных по <a href="/sport/legal/consent" target="_blank" rel="noopener noreferrer">Согласию</a>.
            </label>
            <button type="submit">Подать заявку</button>
        </form>
        """.format(version=html.escape(LEGAL_VERSION, quote=True))
    else:
        applications = ""
        form = (
            '<p class="sport-business__login">Чтобы подключить зал, '
            '<a href="/sport/login?redirect=%2Fsport%2Fbusiness%2Fregister-gym">войдите или зарегистрируйтесь</a>.</p>'
        )

    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Подключить спортивный клуб — Руми</title>
    <meta name="description" content="Подайте заявку, чтобы добавить спортивный клуб в Руми Спорт: страница организации, направления, расписание и абонементы.">
    {get_base_styles()}
</head>
<body class="sport-directory">
    {render_header("sport_business", user)}
    <main class="sport-business">
        <p class="sport-page-eyebrow">Руми Спорт · для бизнеса</p>
        <h1>Подключите спортивный клуб</h1>
        <p class="sport-business__lead">Создайте страницу клуба, добавьте залы, тренеров, направления, расписание и тарифы.
           После проверки клуб появится в каталоге, а заявками и данными можно будет управлять
           из кабинета.</p>
        {success_banner}
        {cta_register}
        {applications}
        <h2 class="sport-business__form-title">Быстрая заявка на подключение</h2>
        {form}
    </main>
    {render_footer(user, sport=True)}
</body>
</html>"""


def render_sport_business_dashboard_page(
    user,
    organizations: list[tuple[SportOrganization, str]],
    success: bool = False,
) -> str:
    status_labels = {
        "pending": "На модерации",
        "approved": "Опубликован",
        "rejected": "Отклонён",
    }
    role_labels = {
        "owner": "Владелец",
        "admin": "Администратор",
        "trainer": "Тренер",
    }
    success_banner = ""
    if success:
        success_banner = """
        <div class="sport-business__success" style="background:var(--color-success-light, #e6f9ed);color:var(--color-success, #12803b);padding:1rem 1.25rem;border-radius:var(--radius-16, 16px);margin-bottom:2rem;font-size:0.95rem;line-height:1.5;">
            <strong>Заявка на подключение клуба принята!</strong><br>
            Клуб отправлен на модерацию. Вы уже можете перейти в управление залом для настройки расписания, тренеров и направлений.
        </div>"""

    cards = "".join(
        '<article class="sport-business__application sport-business-dashboard__card">'
        '<div class="sport-business-dashboard__card-head">'
        f'<h2>{html.escape(organization.name)}</h2>'
        f'<span class="sport-business-dashboard__status sport-business-dashboard__status--'
        f'{html.escape(organization.moderation_status, quote=True)}">'
        f'{html.escape(status_labels.get(organization.moderation_status, organization.moderation_status))}'
        '</span></div>'
        f'<p class="sport-business-dashboard__meta">{html.escape(organization.city)}'
        f'<span>{html.escape(role_labels.get(role, role))}</span></p>'
        + (
            f'<p class="sport-business-dashboard__rejection">{html.escape(organization.rejection_reason)}</p>'
            if organization.rejection_reason else ""
        )
        + f'<a class="sport-business-dashboard__link" href="/sport/{html.escape(organization.slug, quote=True)}/admin">'
        'Открыть панель клуба →</a>'
        + "</article>"
        for organization, role in organizations
    )
    if not cards:
        cards = (
            '<div class="sport-business-dashboard__empty">'
            '<h2>Пока нет подключённых клубов</h2>'
            '<p>Подайте заявку, чтобы создать страницу клуба и управлять расписанием, записями и командой.</p>'
            '<a class="sport-business-dashboard__link" href="/sport/business/register-gym">Подключить клуб →</a>'
            '</div>'
        )
    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Панель спортивного клуба — Руми</title>
    <meta name="description" content="Управление спортивными клубами в Руми Спорт.">
    <meta name="robots" content="noindex,follow">
    {get_base_styles()}
</head>
<body class="sport-directory">
    {render_header("sport_business", user)}
    <main class="sport-business sport-business-dashboard">
        <div class="sport-business-dashboard__intro">
            <p class="sport-page-eyebrow">Руми Спорт · бизнес-панель</p>
            <h1>Ваши клубы</h1>
            <p class="sport-business__lead">Управляйте страницами организаций, расписанием и командой из одного места.</p>
        </div>
        {success_banner}
        <section class="sport-business-dashboard__grid" aria-label="Спортивные клубы">
            {cards}
        </section>
        <a class="sport-business-dashboard__add" href="/sport/business/register-gym">Подключить ещё один клуб</a>
    </main>
    {render_footer(user, sport=True)}
</body>
</html>"""
