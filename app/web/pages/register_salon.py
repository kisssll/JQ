# app/web/pages/register_salon.py
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles


def render_register_salon_page(user=None, error: str = "") -> str:
    """Страница регистрации нового салона (заявка)."""

    error_banner = ""
    if error:
        import html as _html
        error_banner = (
            f'<div style="background:#fde8e8;color:#c0392b;padding:0.75rem 1rem;'
            f'border-radius:0.75rem;margin-bottom:1.5rem;font-size:0.9rem;">'
            f'{_html.escape(error)}</div>'
        )

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Добавить салон — руми</title>
    {get_base_styles()}
</head>
<body>
    {render_header("business")}
    {render_sidebar("business", user)}
    
    <main style="margin-right: 16rem; padding-top: 2rem;">
        <div class="section-container">
            <div class="card" style="max-width: 600px; margin: 0 auto;">
                <h1 class="text-display" style="font-size: 1.75rem; margin-bottom: 0.5rem;">Добавить салон</h1>
                <p class="text-muted" style="margin-bottom: 2rem;">Заполните информацию о вашем салоне. После проверки он появится в каталоге.</p>

                {error_banner}
                <form action="/api/v1/business/my-salon" method="post">
                    <label style="display: block; font-weight: 500; margin-bottom: 0.5rem; color: var(--color-heading);">Название салона *</label>
                    <input type="text" name="name" required placeholder="Например: Студия красоты «Лотос»" style="width: 100%; padding: 0.75rem; border: 1px solid var(--color-border); border-radius: 0.75rem; font-size: 0.95rem; margin-bottom: 1.5rem;">
                    
                    <label style="display: block; font-weight: 500; margin-bottom: 0.5rem; color: var(--color-heading);">Описание</label>
                    <textarea name="description" rows="3" placeholder="Опишите ваш салон, услуги, особенности..." style="width: 100%; padding: 0.75rem; border: 1px solid var(--color-border); border-radius: 0.75rem; font-size: 0.95rem; margin-bottom: 1.5rem; resize: vertical;"></textarea>
                    
                    <label style="display: block; font-weight: 500; margin-bottom: 0.5rem; color: var(--color-heading);">Адрес *</label>
                    <input type="text" name="address" required placeholder="Город, улица, дом" style="width: 100%; padding: 0.75rem; border: 1px solid var(--color-border); border-radius: 0.75rem; font-size: 0.95rem; margin-bottom: 1.5rem;">
                    
                    <label style="display: block; font-weight: 500; margin-bottom: 0.5rem; color: var(--color-heading);">Телефон *</label>
                    <input type="tel" name="phone" value="+7" required placeholder="+7XXXXXXXXXX" style="width: 100%; padding: 0.75rem; border: 1px solid var(--color-border); border-radius: 0.75rem; font-size: 0.95rem; margin-bottom: 1.5rem;">

                    <label style="display: flex; gap: 0.6rem; align-items: flex-start; margin-bottom: 1.5rem; font-size: 0.85rem; cursor: pointer;" class="text-muted">
                        <input type="checkbox" name="offer_accepted" value="1" required style="margin-top: 0.2rem; flex-shrink: 0;">
                        <span>Я принимаю условия оферты и договора-присоединения, даю согласие на обработку персональных данных. Доступ к работе открывается после подтверждения заявки платформой.</span>
                    </label>

                    <button type="submit" class="btn-primary" style="width: 100%; padding: 1rem; font-size: 1rem;">Отправить заявку</button>
                </form>

                <p class="text-muted" style="text-align: center; margin-top: 1rem; font-size: 0.8rem;">Салон появится в каталоге и станет доступен для записи после проверки модератором.</p>
            </div>
        </div>
        {render_footer(user)}
    </main>
</body>
</html>"""
    
    return html