# app/web/pages/model_join.py
"""«Стать моделью» — бесплатная форма включения статуса и редактирования
анкеты (идемпотентно, одна и та же страница/эндпоинт).

Анкета устроена как визард «по одному вопросу за раз» (как в анкетах
знакомств) — фото, о себе и категории услуг. Категории — то же самое поле
model_looking_for, что и раньше: чекбоксы на сабмите схлопываются в строку
через запятую, а при редактировании восстанавливаются эвристикой
match_category_slugs.
"""
from app.web.components.escaping import e

from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.styles import get_base_styles
from app.web.components.icons import ICON_CAMERA
from app.web.service_categories import SERVICE_CATEGORY_GROUPS, match_category_slugs


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
    selected_slugs = set(match_category_slugs(looking_for)) if looking_for else set()

    gallery_cards = "".join(
        f'<div class="model-gallery-item" data-photo-id="{p["id"]}">'
        f'<img src="{p["url"]}" alt="" loading="lazy">'
        f'<button type="button" onclick="window.modelGalleryDelete({p["id"]}, this)">&times;</button>'
        f'</div>'
        for p in (photos or [])
    )

    category_options = "".join(
        f'<label class="category-option mj-category-option" data-slug="{slug}">'
        f'<input type="checkbox" name="model-category" value="{slug}" data-label="{e(label)}"'
        f'{" checked" if slug in selected_slugs else ""}> {e(label)}</label>'
        for slug, label, _kw in SERVICE_CATEGORY_GROUPS
    )

    categories_button = f'<button type="submit" class="mj-next-btn">{submit_label}</button>'

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title} | Руми</title>
    {get_base_styles()}
</head>
<body>
    {render_header("model", user)}

    <main class="main-content" style="padding:2rem 1.5rem 3rem;max-width:760px;box-sizing:border-box">
        <h1 style="margin-bottom:0.5rem">{ICON_CAMERA} {title}</h1>
        <p class="text-muted" style="margin-bottom:1.5rem">Участие в моделинге бесплатное. Заполните анкету, чтобы мастера могли приглашать вас на отработку техник.</p>
        {error_html}

        <form id="modelJoinForm" class="card" style="padding:1.5rem" enctype="multipart/form-data">
            <div class="mj-progress-label" id="mjProgressLabel"></div>
            <div class="mj-progress-track"><div class="mj-progress-fill" id="mjProgressFill"></div></div>

            <div class="mj-step" data-step="photo">
                <div class="mj-step-h"><span class="mj-step-num">1</span><h2>Ваше фото</h2></div>
                <p class="mj-hint">Мастера в первую очередь смотрят на фото анкеты — выберите чёткое, где хорошо видно лицо и причёску.</p>
                <div style="display:flex;align-items:center;gap:1rem">
                    <img id="modelJoinPreview" src="{e(photo or 'https://placehold.co/96x96')}" alt="" style="width:96px;height:96px;border-radius:50%;object-fit:cover">
                    <div>
                        <label for="modelJoinPhoto" class="btn-outline" style="cursor:pointer;display:inline-block;padding:0.5rem 1rem">Загрузить фото</label>
                        <input type="file" id="modelJoinPhoto" name="photo" accept="image/*" style="display:none">
                    </div>
                </div>
                <div class="mj-step-actions">
                    <button type="button" class="mj-next-btn mj-next" data-next="bio">Далее</button>
                </div>
            </div>

            <div class="mj-step" data-step="bio" style="display:none">
                <button type="button" class="mj-back-btn mj-back" data-to="photo">← Назад</button>
                <div class="mj-step-h"><span class="mj-step-num">2</span><h2>О себе</h2></div>
                <p class="mj-hint">Расскажите про рост, особенности внешности, опыт съёмок или тестовых работ — это первое, что читают мастера.</p>
                <textarea name="bio" rows="4" placeholder="Расскажите о себе — рост, особенности внешности, опыт..." style="width:100%;padding:0.6rem;border:1px solid var(--color-border);border-radius:var(--radius-8)">{e(bio)}</textarea>
                <div class="mj-step-actions">
                    <button type="button" class="mj-next-btn mj-next" data-next="categories">Далее</button>
                </div>
            </div>

            <div class="mj-step" data-step="categories" style="display:none">
                <button type="button" class="mj-back-btn mj-back" data-to="bio">← Назад</button>
                <div class="mj-step-h"><span class="mj-step-num">3</span><h2>Какие услуги вам интересны</h2></div>
                <p class="mj-hint">Отметьте направления, в которых хотите быть моделью, — мастера чаще приглашают по совпадающим категориям.</p>
                <div class="mj-category-grid">{category_options}</div>
                <textarea name="looking_for" id="modelLookingFor" style="display:none">{e(looking_for)}</textarea>
                <div class="mj-step-actions">
                    {categories_button}
                </div>
            </div>
        </form>

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
        .model-gallery-item img {{ width:100%; height:100%; object-fit:cover; border-radius:var(--radius-16) }}
        .model-gallery-item button {{ position:absolute; top:-0.4rem; right:-0.4rem; width:1.5rem; height:1.5rem; border-radius:50%; border:none; background:var(--color-danger); color:var(--color-on-status); cursor:pointer; font-size:0.9rem; line-height:1 }}
        .mj-progress-label {{ font-size:0.8rem; color:var(--color-muted); margin-bottom:0.5rem }}
        .mj-progress-track {{ height:4px; background:var(--color-border); border-radius:var(--radius-8); overflow:hidden; margin-bottom:1.5rem }}
        .mj-progress-fill {{ height:100%; width:0; background:var(--color-primary); transition:width 0.25s ease }}
        .mj-step-h {{ display:flex; align-items:center; gap:0.6rem; margin:0 0 0.5rem }}
        .mj-step-num {{ width:26px; height:26px; border-radius:50%; background:var(--color-primary); color:var(--color-on-dark); font-size:0.8rem; font-weight:700; display:flex; align-items:center; justify-content:center; flex-shrink:0 }}
        .mj-step-h h2 {{ font-size:1.05rem; margin:0; font-weight:600 }}
        .mj-hint {{ color:var(--color-muted); font-size:0.85rem; margin:0 0 0.9rem }}
        .mj-back-btn {{ background:none; border:none; color:var(--color-muted); cursor:pointer; padding:0; margin-bottom:0.75rem; font-size:0.85rem }}
        .mj-back-btn:hover {{ color:var(--color-accent-text) }}
        /* justify-content:flex-end тут нарочно НЕ используем — <main> не
           резервирует место под фиксированный сайдбар (у него нет ширины
           #main-content под это, position:fixed сайдбара не участвует в
           потоке), и кнопка, прижатая к правому краю широкого контейнера,
           на десктопе уезжает под сайдбар и перекрывается им (z-index выше).
           Прижимаем к левому краю — там всегда видно, и на мобиле тоже. */
        .mj-step-actions {{ display:flex; gap:0.75rem; margin-top:1.25rem }}
        /* Явные inline-подобные значения (с фолбэком у var()) вместо общих
           .btn-primary/.btn-outline — кнопки шагов визарда не должны зависеть
           от того, что где-то ещё на странице переопределит эти классы. */
        .mj-next-btn {{
            display:inline-flex; align-items:center; justify-content:center;
            background:linear-gradient(135deg, var(--color-primary), var(--color-accent-hover));
            color:var(--color-on-dark) !important; padding:10px 24px; border-radius:var(--radius-pill); border:none;
            font-weight:600; font-size:0.95rem; cursor:pointer; opacity:1; visibility:visible;
        }}
        .mj-next-btn:hover {{ opacity:0.92 }}
        .mj-category-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(11rem,1fr)); gap:0.5rem }}
        .mj-category-option {{ border:1px solid var(--color-border); border-radius:var(--radius-16); white-space:normal }}
        .mj-category-option:has(input:checked) {{ border-color:var(--color-primary); background:color-mix(in srgb, var(--color-primary) 8%, transparent) }}

        /* На десктопе сайдбар уже даёт всю навигацию, а гамбургер из шапки
           скрыт (>=1024px) — сама плашка с лого только перекрывает заголовок
           анкеты (#main-header зафиксирован поверх страницы). На мобиле
           шапку оставляем — там гамбургер единственный способ открыть меню. */
        @media (min-width: 1024px) {{
            #main-header {{ display: none; }}
        }}
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

        const form = document.getElementById('modelJoinForm');
        const steps = Array.from(form.querySelectorAll('.mj-step'));
        const stepIds = steps.map(s => s.dataset.step);
        const progressFill = document.getElementById('mjProgressFill');
        const progressLabel = document.getElementById('mjProgressLabel');

        function goToStep(id) {{
            const idx = stepIds.indexOf(id);
            if (idx === -1) return;
            steps.forEach(s => {{ s.style.display = (s.dataset.step === id ? '' : 'none'); }});
            progressFill.style.width = ((idx + 1) / stepIds.length * 100) + '%';
            progressLabel.textContent = 'Шаг ' + (idx + 1) + ' из ' + stepIds.length;
            form.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
        }}

        form.querySelectorAll('.mj-next').forEach(btn => {{
            btn.addEventListener('click', () => goToStep(btn.dataset.next));
        }});
        form.querySelectorAll('.mj-back').forEach(btn => {{
            btn.addEventListener('click', () => goToStep(btn.dataset.to));
        }});
        goToStep(stepIds[0]);

        form.addEventListener('submit', async function(e) {{
            e.preventDefault();
            const checkedCategories = Array.from(form.querySelectorAll('input[name="model-category"]:checked'));
            document.getElementById('modelLookingFor').value = checkedCategories.map(cb => cb.dataset.label).join(', ');

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
                window.location.href = '/model/dashboard';
            }} catch (err) {{
                alert('Ошибка соединения с сервером');
                btn.disabled = false;
            }}
        }});

    }})();
    </script>
</body>
</html>"""
