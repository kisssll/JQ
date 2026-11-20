import html

from app.models.sport import SportOrganization
from app.web.components.footer import render_footer
from app.web.components.header import render_header
from app.web.components.styles import get_base_styles
from app.web.pages.legal import LEGAL_VERSION


def render_sport_business_page(user=None, organizations: list[SportOrganization] | None = None) -> str:
    organizations = organizations or []
    status_labels = {
        "pending": "На модерации",
        "approved": "Одобрен",
        "rejected": "Отклонён",
    }
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
                Принимаю <a href="/license" target="_blank" rel="noopener noreferrer">условия для спортивных клубов</a>.
            </label>
            <label class="sport-business__check">
                <input type="checkbox" name="pd_consent" value="1" required>
                Согласен(на) на обработку персональных данных по <a href="/consent" target="_blank" rel="noopener noreferrer">Согласию</a>.
            </label>
            <button type="submit">Подать заявку</button>
        </form>
        """.format(version=html.escape(LEGAL_VERSION, quote=True))
    else:
        applications = ""
        form = (
            '<p class="sport-business__login">Чтобы подключить зал, '
            '<a href="/login?redirect=%2Fsport%2Fbusiness">войдите или зарегистрируйтесь</a>.</p>'
        )

    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Подключить спортивный клуб — Руми</title>
    {get_base_styles()}
    <style>
        .sport-business{{max-width:760px;margin:48px auto;padding:0 20px 72px}}
        .sport-business__form{{display:grid;gap:16px;margin-top:28px}}
        .sport-business__form label{{display:grid;gap:6px}}
        .sport-business__form input,.sport-business__form textarea{{font:inherit;padding:12px;border:1px solid #d5d5d5;border-radius:8px}}
        .sport-business__form textarea{{min-height:110px}}
        .sport-business__form .sport-business__check{{display:flex;align-items:flex-start;gap:10px}}
        .sport-business__form .sport-business__check input{{margin-top:5px}}
        .sport-business__form button{{justify-self:start;padding:13px 22px;border:0;border-radius:999px;background:#1a1a1a;color:white;font:inherit;cursor:pointer}}
        .sport-business__application{{padding:16px 0;border-bottom:1px solid #ddd}}
        .sport-business__login{{margin-top:24px}}
    </style>
</head>
<body>
    {render_header("sport_business", user)}
    <main class="sport-business">
        <p>Руми Спорт · для бизнеса</p>
        <h1>Подключите спортивный клуб</h1>
        <p>Создайте страницу клуба, добавьте залы, тренеров, направления, расписание и тарифы.
           После проверки клуб появится в каталоге, а заявками и данными можно будет управлять
           из кабинета.</p>
        {applications}
        <h2>Заявка на подключение</h2>
        {form}
    </main>
    {render_footer(user)}
</body>
</html>"""


def render_sport_business_dashboard_page(user, organizations: list[tuple[SportOrganization, str]]) -> str:
    status_labels = {
        "pending": "На модерации",
        "approved": "Опубликован",
        "rejected": "Отклонён",
    }
    cards = "".join(
        '<article class="sport-business__application">'
        f'<h2>{html.escape(organization.name)}</h2>'
        f'<p>{html.escape(organization.city)} · {html.escape(status_labels.get(organization.moderation_status, organization.moderation_status))}'
        f' · роль: {html.escape(role)}</p>'
        + (
            f'<p>{html.escape(organization.rejection_reason)}</p>'
            if organization.rejection_reason else ""
        )
        + f'<a href="/sport/{html.escape(organization.slug, quote=True)}/admin">Открыть панель клуба</a>'
        + "</article>"
        for organization, role in organizations
    )
    if not cards:
        cards = (
            '<p>У вас пока нет доступа к панели спортивного клуба. '
            '<a href="/sport/business">Подключить клуб</a>.</p>'
        )
    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Панель спортивного клуба — Руми</title>
    {get_base_styles()}
    <style>
        .sport-business{{max-width:900px;margin:48px auto;padding:0 20px 72px}}
        .sport-business__application{{padding:20px 0;border-bottom:1px solid #ddd}}
        .sport-business__application h2{{margin:0 0 8px}}
    </style>
</head>
<body>
    {render_header("sport_business", user)}
    <main class="sport-business">
        <p>Руми Спорт · бизнес-панель</p>
        <h1>Ваши спортивные клубы</h1>
        {cards}
        <p><a href="/sport/business">Подключить ещё один клуб</a></p>
    </main>
    {render_footer(user)}
</body>
</html>"""
