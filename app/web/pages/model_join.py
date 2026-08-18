# app/web/pages/model_join.py
"""«Стать моделью» — форма первичного включения статуса и последующего
редактирования анкеты (идемпотентно, одна и та же страница/эндпоинт)."""
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.sidebar import render_sidebar
from app.web.components.styles import get_base_styles
from app.web.components.icons import ICON_CAMERA


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

        document.getElementById('modelJoinForm').addEventListener('submit', async function(e) {{
            e.preventDefault();
            const formData = new FormData(e.target);
            try {{
                const res = await fetch('/api/v1/model-matching/profile', {{ method: 'POST', body: formData }});
                if (res.ok) {{
                    window.location.href = '/model/dashboard';
                }} else {{
                    const data = await res.json().catch(() => ({{}}));
                    alert(data.detail || 'Не удалось сохранить анкету');
                }}
            }} catch (err) {{
                alert('Ошибка соединения с сервером');
            }}
        }});
    }})();
    </script>
</body>
</html>"""
