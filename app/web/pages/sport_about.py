# app/web/pages/sport_about.py
"""Страница «Манифест» Руми Спорт."""
from app.web.components import ui
from app.web.components.escaping import e
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.styles import get_base_styles
from app.web.pages.about import _render_tbank_news

REMOVED = [
    "Звонки в клуб",
    "Голосовая почта",
    "Ожидание на линии",
    "Уточнения по СМС",
    "Десять полей в форме",
    "Регистрации, которые ни на что не влияют",
]


def render_sport_about_page(user=None) -> str:
    """Страница «Манифест» Руми Спорт в спортивном оформлении."""
    removed = "".join(f"<li>{e(r)}</li>" for r in REMOVED)
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Манифест | Руми Спорт</title>
    <meta name="description" content="Мы убрали из спорта всё лишнее. Остались вы и тренер.">
    {get_base_styles()}
</head>
<body class="sport-directory sport-about">
    {render_header("sport_manifest", user)}

    <main class="about-main">
        <section class="about-hero">
            <div class="section-container">
                <span class="about-kicker">Манифест</span>
                <h1 class="about-title">Мы убрали из спорта всё лишнее. Остались <em>вы и тренер</em>.</h1>
            </div>
        </section>

        <section class="about-body">
            <div class="section-container">
                <div class="about-cols">
                    <p class="about-drop">Раньше, чтобы записаться на тренировку, нужно было найти клуб и номер, дозвониться, объяснить, кто вы и в какую группу хотите, и запомнить время занятия.</p>
                    <p>Теперь — четыре клика. <b>Клуб. Тренировка. Время. Готово.</b> Всё остальное мы оставили на своей стороне: расписание, напоминания, оплату, общение с тренером, аналитику для клуба.</p>
                </div>

                <h2 class="about-removed-title">Что мы <em>убрали</em></h2>
                <ul class="about-removed">{removed}</ul>

                <blockquote class="about-quote">Для клиентов — 4 клика до тренировки. Для клубов — всё для управления в одном окне.</blockquote>
                <div class="about-cta">{ui.button("Найти клуб", href="/sport/clubs")}</div>
            </div>
        </section>

        {_render_tbank_news()}

        {render_footer(user, sport=True)}
    </main>
</body>
</html>"""
