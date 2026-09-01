# app/web/pages/about.py
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.components.tbank import render_tbank_products_block


def render_about_page(user=None) -> str:
    """Страница «Манифест»."""

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Манифест | руми.</title>
    <meta name="description" content="Мы убрали из красоты всё лишнее. Остались вы и мастер.">
    {get_base_styles()}
</head>
<body>
    {render_header("manifest")}
    {render_sidebar("manifest", user)}

    <main class="home-main">
        <section class="about-hero">
            <div class="section-container">
                <p class="about-label">Манифест</p>
                <h1 class="about-title">Мы убрали из красоты всё лишнее. Остались вы и мастер<span class="about-dot">.</span></h1>
    
                <div class="about-grid">
                    <div class="about-text">
                        <p class="about-text-p">Раньше, чтобы записаться к парикмахеру, нужно было найти мастера и номер, дозвониться, объяснить, кто вы и что хотите, и запомнить время записи.</p>
                        <p class="about-text-p">Теперь — четыре клика. Салон. Услуга. Время. Готово. Всё остальное мы оставили на своей стороне: расписание, напоминания, оплату, общение с мастером, аналитику для салона.</p>
                    </div>
                    <div class="about-list">
                        <p class="about-list-label">Что мы убрали</p>
                        <ul class="about-list-items">
                            <li><span class="about-list-bullet"></span>Звонки в салон</li>
                            <li><span class="about-list-bullet"></span>Голосовая почта</li>
                            <li><span class="about-list-bullet"></span>Ожидание на линии</li>
                            <li><span class="about-list-bullet"></span>Уточнения по СМС</li>
                            <li><span class="about-list-bullet"></span>Десять полей в форме</li>
                            <li><span class="about-list-bullet"></span>Регистрации, которые ни на что не влияют</li>
                        </ul>
                    </div>
                </div>

                <div class="about-footer">
                    <p class="about-footer-text">Для клиентов — 4 клика до записи. Для салонов — всё для управления в одном окне.</p>
                    <div class="about-footer-buttons">
                        <a href="/salons" class="about-btn-primary">Найти салон</a>
                    </div>
                </div>

                {render_tbank_products_block()}
            </div>
        </section>

        {render_footer(user)}
    </main>
</body>
</html>"""
    return html