# app/web/pages/model_join.py
"""«Стать моделью» — форма первичного включения статуса и последующего
редактирования анкеты (идемпотентно, одна и та же страница/эндпоинт).

Первый раз (is_model=False) — форма анкеты + выбор тарифа (см.
app.services.tariffs.MODEL_TARIFF_CATALOG, цены — как на /model#plans):
сохранение анкеты создаёт профиль, следом сразу идёт оплата/старт триала
(/api/v1/payments/model/init) — активной в ленте мастеров (require_approved_model)
модель становится только после модерации И оплаты, см. app/api/deps.py.
Дальше (is_model=True) — тот же экран показывает текущий статус подписки и
кнопки «Оплатить»/«Отменить автопродление» вместо выбора тарифа.
"""
from datetime import datetime, timezone

from app.core.config import settings
from app.models.models import SalonSubscriptionStatus
from app.services.tariffs import MODEL_TARIFF_CATALOG
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.components.icons import ICON_CAMERA

_STATUS_LABELS = {
    SalonSubscriptionStatus.NONE: ("Тариф не выбран", "var(--color-muted)"),
    SalonSubscriptionStatus.TRIALING: ("Пробный период", "#f59e0b"),
    SalonSubscriptionStatus.ACTIVE: ("Активна", "#22c55e"),
    SalonSubscriptionStatus.PAST_DUE: ("Платёж не прошёл", "#ef4444"),
    SalonSubscriptionStatus.CANCELED: ("Отменена", "var(--color-muted)"),
}


def _billing_section_html(user) -> str:
    """Статус подписки + «Оплатить»/«Отменить автопродление» — только для
    уже действующих моделей (is_model=True). Первичный выбор тарифа —
    отдельный блок _tariff_selector_html, показывается ДО первого сохранения."""
    status = user.subscription_status
    label, color = _STATUS_LABELS.get(status, ("—", "var(--color-muted)"))
    tariff = MODEL_TARIFF_CATALOG.get(user.subscription_tier.value) if user.subscription_tier else None
    plan_name = tariff.name if tariff else "—"

    date_fmt = "%d.%m.%Y"
    lines = [f'<span style="color:{color};font-weight:600">{label}</span>']
    if status == SalonSubscriptionStatus.TRIALING and user.trial_ends_at:
        lines.append(f"до {user.trial_ends_at.strftime(date_fmt)}")
    elif status in (SalonSubscriptionStatus.ACTIVE, SalonSubscriptionStatus.PAST_DUE, SalonSubscriptionStatus.CANCELED) and user.subscription_expires_at:
        lines.append(f"доступ до {user.subscription_expires_at.strftime(date_fmt)}")
    status_line = " · ".join(lines)

    renew_line = ""
    if user.auto_renew:
        renew_line = '<p class="text-muted" style="margin:0.25rem 0 0;font-size:0.85rem">Автопродление включено'
        if user.card_last4:
            renew_line += f" · карта •• {user.card_last4}"
        renew_line += "</p>"

    if not settings.TKASSA_ENABLED:
        actions_html = '<p class="text-muted" style="margin-top:1rem;font-size:0.85rem">Оплата картой скоро появится.</p>'
    else:
        cancel_btn = (
            '<button id="modelCancelBtn" class="btn-outline" '
            'style="padding:0.65rem 1.4rem;border-radius:0.6rem">Отменить автопродление</button>'
            if user.auto_renew else ""
        )
        actions_html = (
            f'<div style="display:flex;gap:0.75rem;flex-wrap:wrap;margin-top:1.25rem">'
            f'<button id="modelPayBtn" class="btn-primary" style="padding:0.65rem 1.4rem;border-radius:0.6rem">Оплатить</button>'
            f'{cancel_btn}</div>'
            f'<p class="checkout-note" id="model-billing-note" style="margin-top:0.75rem;min-height:1.2em"></p>'
        )

    return f"""
    <div class="card" style="padding:1.5rem;margin-top:1rem">
        <h3 style="margin:0 0 0.5rem">Тариф «{plan_name}»</h3>
        <p style="margin:0">{status_line}</p>
        {renew_line}
        {actions_html}
    </div>"""


def _tariff_selector_html() -> str:
    """Выбор тарифа при первом заполнении анкеты — компактные карточки,
    цены синхронизированы с MODEL_TARIFF_CATALOG (те же, что на /model#plans)."""
    cards = "".join(
        f"""
        <label class="model-tariff-card" data-plan="{t.plan}">
            <input type="radio" name="model-plan" value="{t.plan}" {"checked" if t.plan == "start" else ""}>
            <span class="model-tariff-name">{t.name}</span>
            <span class="model-tariff-price">{int(t.amount)} ₽<span class="model-tariff-period">/мес</span></span>
        </label>"""
        for t in MODEL_TARIFF_CATALOG.values()
    )
    renewal_html = ""
    if settings.TKASSA_ENABLED:
        renewal_html = """
        <div id="model-renewal-mode-wrap" style="margin-top:1rem">
            <label class="form-label">Продление подписки</label>
            <label class="checkbox-label">
                <input type="radio" name="model-renewal-mode" value="auto" class="checkbox-input" checked>
                <span class="checkbox-text">Автоматически каждый месяц (можно отменить в любой момент)</span>
            </label>
            <label class="checkbox-label">
                <input type="radio" name="model-renewal-mode" value="manual" class="checkbox-input">
                <span class="checkbox-text">Буду продлевать вручную</span>
            </label>
        </div>"""
    note = (
        "Первые 14 дней — бесплатно. Без выбранного тарифа анкета не появится в подборках у мастеров."
        if settings.TKASSA_ENABLED else
        "Пока тариф активируется сразу на пробный период — оплата картой скоро появится."
    )
    return f"""
    <div class="card" style="padding:1.5rem;margin-top:1rem">
        <h3 style="margin:0 0 0.75rem">Выберите тариф</h3>
        <div class="model-tariff-grid">{cards}</div>
        {renewal_html}
        <p class="checkout-note" style="margin-top:0.75rem">{note}</p>
    </div>"""


def render_model_join_page(user, error: str | None = None, photos: list[dict] | None = None) -> str:
    is_model = bool(getattr(user, "is_model", False))
    title = "Редактировать анкету модели" if is_model else "Стать моделью"
    submit_label = "Сохранить" if is_model else "Стать моделью"

    error_html = ""
    if error:
        error_html = f'<div class="profile-alert profile-alert-error">{error}</div>'

    photo = getattr(user, "model_photo_url", None) or ""
    bio = getattr(user, "model_bio", "") or ""
    looking_for = getattr(user, "model_looking_for", "") or ""

    gallery_cards = "".join(
        f'<div class="model-gallery-item" data-photo-id="{p["id"]}">'
        f'<img src="{p["url"]}" alt="" loading="lazy">'
        f'<button type="button" onclick="window.modelGalleryDelete({p["id"]}, this)">&times;</button>'
        f'</div>'
        for p in (photos or [])
    )

    billing_html = _billing_section_html(user) if is_model else _tariff_selector_html()

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title} | Руми</title>
    {get_base_styles()}
</head>
<body>
    {render_header("model")}
    {render_sidebar("model", user)}

    <main class="section-container-sm" style="padding-top:2rem;padding-bottom:3rem">
        <h1 style="margin-bottom:0.5rem">{ICON_CAMERA} {title}</h1>
        <p class="text-muted" style="margin-bottom:1.5rem">Мастера ищут моделей, чтобы отработать технику или пополнить портфолио — вы получаете услугу со скидкой или бесплатно.</p>
        {error_html}

        <form id="modelJoinForm" class="card" style="padding:1.5rem;display:flex;flex-direction:column;gap:1rem" enctype="multipart/form-data">
            <div style="display:flex;align-items:center;gap:1rem">
                <img id="modelJoinPreview" src="{photo or 'https://placehold.co/96x96'}" alt="" style="width:96px;height:96px;border-radius:50%;object-fit:cover">
                <div>
                    <label for="modelJoinPhoto" class="btn-outline" style="cursor:pointer;display:inline-block;padding:0.5rem 1rem">Загрузить фото</label>
                    <input type="file" id="modelJoinPhoto" name="photo" accept="image/*" style="display:none">
                </div>
            </div>
            <div>
                <label style="display:block;font-weight:500;margin-bottom:0.4rem">О себе</label>
                <textarea name="bio" rows="4" placeholder="Расскажите о себе — рост, особенности внешности, опыт..." style="width:100%;padding:0.6rem;border:1px solid var(--color-border);border-radius:0.5rem">{bio}</textarea>
            </div>
            <div>
                <label style="display:block;font-weight:500;margin-bottom:0.4rem">Что вы ищете</label>
                <textarea name="looking_for" rows="3" placeholder="Например: стрижка, окрашивание, маникюр..." style="width:100%;padding:0.6rem;border:1px solid var(--color-border);border-radius:0.5rem">{looking_for}</textarea>
            </div>
            <button type="submit" class="btn-primary">{submit_label}</button>
        </form>

        {billing_html}

        <div class="card" style="padding:1.5rem;margin-top:1rem">
            <h3 style="margin-bottom:0.5rem">Галерея (до 6 фото)</h3>
            <p class="text-muted" style="font-size:0.85rem;margin-bottom:1rem">Салоны увидят эти фото в вашей анкете — чем больше ракурсов, тем лучше.</p>
            <div id="modelGalleryGrid" class="model-gallery-grid">{gallery_cards}</div>
            <label for="modelGalleryInput" class="btn-outline" style="cursor:pointer;display:inline-block;margin-top:0.75rem">+ Добавить фото</label>
            <input type="file" id="modelGalleryInput" accept="image/*" multiple style="display:none">
        </div>
    </main>
    {render_footer(user)}

    <style>
        .model-gallery-grid {{ display:flex; flex-wrap:wrap; gap:0.75rem }}
        .model-gallery-item {{ position:relative; width:96px; height:96px }}
        .model-gallery-item img {{ width:100%; height:100%; object-fit:cover; border-radius:0.75rem }}
        .model-gallery-item button {{ position:absolute; top:-0.4rem; right:-0.4rem; width:1.5rem; height:1.5rem; border-radius:50%; border:none; background:#ef4444; color:#fff; cursor:pointer; font-size:0.9rem; line-height:1 }}
        .model-tariff-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(9rem,1fr)); gap:0.75rem }}
        .model-tariff-card {{ display:flex; flex-direction:column; align-items:center; gap:0.3rem; padding:0.9rem 0.6rem; border:1px solid var(--color-border); border-radius:0.75rem; cursor:pointer; text-align:center }}
        .model-tariff-card:has(input:checked) {{ border-color:var(--color-primary); background:color-mix(in srgb, var(--color-primary) 8%, transparent) }}
        .model-tariff-card input {{ accent-color:var(--color-primary) }}
        .model-tariff-name {{ font-weight:600 }}
        .model-tariff-price {{ font-size:1.1rem; font-weight:700; color:var(--color-primary) }}
        .model-tariff-period {{ font-size:0.75rem; font-weight:400; color:var(--color-muted) }}
    </style>

    <script>
    (function() {{
        const photoInput = document.getElementById('modelJoinPhoto');
        const preview = document.getElementById('modelJoinPreview');
        photoInput.addEventListener('change', function() {{
            if (photoInput.files[0]) {{
                preview.src = URL.createObjectURL(photoInput.files[0]);
            }}
        }});

        const galleryInput = document.getElementById('modelGalleryInput');
        const galleryGrid = document.getElementById('modelGalleryGrid');
        galleryInput.addEventListener('change', async function() {{
            if (!galleryInput.files.length) return;
            const formData = new FormData();
            for (const f of galleryInput.files) formData.append('files', f);
            try {{
                const res = await fetch('/api/v1/upload/model/photo', {{ method: 'POST', body: formData }});
                const data = await res.json().catch(() => ({{}}));
                if (data.errors && data.errors.length) {{
                    alert(data.errors[0].detail);
                }}
                if (data.saved && data.saved.length) {{
                    location.reload();
                }}
            }} catch (err) {{
                alert('Ошибка соединения с сервером');
            }} finally {{
                galleryInput.value = '';
            }}
        }});

        window.modelGalleryDelete = async function(photoId, btn) {{
            try {{
                const res = await fetch('/api/v1/upload/model/photo/' + photoId + '/delete', {{ method: 'POST' }});
                if (res.ok) {{
                    btn.closest('.model-gallery-item').remove();
                }} else {{
                    alert('Не удалось удалить фото');
                }}
            }} catch (err) {{
                alert('Ошибка соединения с сервером');
            }}
        }};

        const isModel = {"true" if is_model else "false"};
        const tkassaEnabled = {"true" if settings.TKASSA_ENABLED else "false"};

        document.getElementById('modelJoinForm').addEventListener('submit', async function(e) {{
            e.preventDefault();
            const btn = e.target.querySelector('button[type="submit"]');
            btn.disabled = true;
            const formData = new FormData(e.target);
            try {{
                const res = await fetch('/api/v1/model-matching/profile', {{ method: 'POST', body: formData }});
                if (!res.ok) {{
                    const data = await res.json().catch(() => ({{}}));
                    alert(data.detail || 'Не удалось сохранить анкету');
                    btn.disabled = false;
                    return;
                }}
                if (isModel) {{
                    // Редактирование анкеты уже действующей модели — тариф не трогаем.
                    window.location.href = '/model/dashboard';
                    return;
                }}
                // Первое сохранение — сразу запускаем триал/оплату выбранного тарифа.
                const plan = document.querySelector('input[name="model-plan"]:checked').value;
                const renewalInput = document.querySelector('input[name="model-renewal-mode"]:checked');
                const autoRenew = tkassaEnabled && (!renewalInput || renewalInput.value === 'auto');
                const initRes = await fetch('/api/v1/payments/model/init', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ plan: plan, auto_renew: autoRenew }}),
                }});
                const initData = await initRes.json().catch(() => ({{}}));
                if (!initRes.ok) {{
                    alert(initData.detail || 'Анкета сохранена, но не удалось подключить тариф — откройте эту страницу ещё раз.');
                    window.location.href = '/model/dashboard';
                    return;
                }}
                window.location.href = initData.requires_payment ? initData.payment_url : (initData.redirect || '/model/dashboard');
            }} catch (err) {{
                alert('Ошибка соединения с сервером');
                btn.disabled = false;
            }}
        }});

        const note = document.getElementById('model-billing-note');
        const setNote = (text) => {{ if (note) note.textContent = text; }};

        const payBtn = document.getElementById('modelPayBtn');
        if (payBtn) {{
            payBtn.addEventListener('click', async function() {{
                this.disabled = true;
                setNote('Готовим оплату…');
                try {{
                    const res = await fetch('/api/v1/payments/model/manual-charge', {{ method: 'POST' }});
                    const data = await res.json().catch(() => ({{}}));
                    if (!res.ok) {{
                        setNote(data.detail || 'Не удалось подготовить оплату.');
                        this.disabled = false;
                        return;
                    }}
                    setNote('Переходим к оплате…');
                    window.location = data.payment_url;
                }} catch (err) {{
                    setNote('Ошибка сети, попробуйте ещё раз.');
                    this.disabled = false;
                }}
            }});
        }}

        const cancelBtn = document.getElementById('modelCancelBtn');
        if (cancelBtn) {{
            cancelBtn.addEventListener('click', async function() {{
                if (!confirm('Отключить автопродление? Доступ по уже оплаченному периоду сохранится.')) return;
                this.disabled = true;
                setNote('Отключаем автопродление…');
                try {{
                    const res = await fetch('/api/v1/payments/model/cancel-auto-renew', {{ method: 'POST' }});
                    if (res.ok) {{
                        window.location.reload();
                    }} else {{
                        const data = await res.json().catch(() => ({{}}));
                        setNote(data.detail || 'Не удалось отключить автопродление.');
                        this.disabled = false;
                    }}
                }} catch (err) {{
                    setNote('Ошибка сети, попробуйте ещё раз.');
                    this.disabled = false;
                }}
            }});
        }}

        const paymentParam = new URLSearchParams(window.location.search).get('payment');
        if (paymentParam === 'success') {{
            setNote('Оплата прошла — статус обновится в течение минуты.');
        }} else if (paymentParam === 'fail') {{
            setNote('Оплата не прошла — попробуйте ещё раз.');
        }}
    }})();
    </script>
</body>
</html>"""
