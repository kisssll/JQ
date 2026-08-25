# app/web/views.py
from app.web.components.escaping import e
import html
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.core.config import settings
from app.models.models import Salon, User, Master, Service as ServiceModel
from app.services.subscription import access_clause
from app.web.pages.home import render_home_page
from app.web.pages.login import render_login_page         
from app.web.pages.register import render_register_page
from app.web.pages.model_landing import render_model_landing_page
from app.web.pages.model_join import render_model_join_page
from app.web.pages.about import render_about_page
from app.web.pages.legal import render_legal_page
from app.web.pages.business_landing import render_business_landing_page
from app.web.components.header import render_header
from app.web.components.footer import render_footer
from app.web.components.styles import get_base_styles
from app.web.components.sidebar import render_sidebar
from app.web.auth import get_current_user_from_cookie
from app.web.components.icons import (
    ICON_BUILDING2,
    ICON_CALENDAR_DAYS,
    ICON_CAMERA,
    ICON_CLOCK,
    ICON_HOUSE,
    ICON_MONEY,
    ICON_SCISSORS,
)


router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Главная страница."""
    user = await get_current_user_from_cookie(request, db)
    html = await render_home_page(db, user)
    return HTMLResponse(content=html)


@router.get("/salons", response_class=HTMLResponse)
async def salons_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Страница со списком салонов (серверные фильтры/поиск/сортировка).
    ?partial=1 → только сетка карточек (для AJAX-подмены на фронт-этапе)."""
    user = await get_current_user_from_cookie(request, db)
    from app.web.pages.salons import render_salons_page, parse_salon_query
    params = parse_salon_query(request)
    partial = request.query_params.get("partial") == "1"
    page_html = await render_salons_page(db, user, params, partial)
    return HTMLResponse(content=page_html)


@router.get("/evening-deals", response_class=HTMLResponse)
async def evening_deals_page(request: Request, city: str = None, db: AsyncSession = Depends(get_db)):
    """Публичная подборка «вечерние окна со скидкой» (ссылка из ТГ-рассылки)."""
    user = await get_current_user_from_cookie(request, db)
    from app.web.pages.evening_deals import render_evening_deals_page
    html = await render_evening_deals_page(db, city, user)
    return HTMLResponse(content=html)


@router.get("/salons/{salon_id}", response_class=HTMLResponse)
async def salon_detail_page(salon_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Страница конкретного салона."""
    user = await get_current_user_from_cookie(request, db)
    from app.web.pages.salon_detail import render_salon_detail
    html = await render_salon_detail(db, salon_id, user)
    return HTMLResponse(content=html)


@router.get("/masters/{master_id}", response_class=HTMLResponse)
async def master_detail_page(master_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Страница конкретного мастера."""
    user = await get_current_user_from_cookie(request, db)
    from app.web.pages.master_detail import render_master_detail
    html = await render_master_detail(db, master_id, user)
    return HTMLResponse(content=html)


@router.get("/book/{salon_id}", response_class=HTMLResponse)
async def guest_booking_page(salon_id: int, db: AsyncSession = Depends(get_db)):
    """Публичная запись без регистрации (по ссылке/QR салона)."""
    from app.web.pages.guest_booking import render_guest_booking_page
    return HTMLResponse(content=await render_guest_booking_page(db, salon_id))


@router.get("/guest-booking/{token}", response_class=HTMLResponse)
async def guest_manage_page(token: str, db: AsyncSession = Depends(get_db)):
    """Просмотр/отмена гостевой брони по токену."""
    from app.web.pages.guest_booking import render_guest_manage_page
    return HTMLResponse(content=await render_guest_manage_page(db, token))


@router.get("/book/{salon_id}/qr")
async def guest_booking_qr(salon_id: int, request: Request):
    """PNG QR-код на публичную страницу записи салона (для печати на ресепшене)."""
    import io
    import qrcode
    from fastapi import Response

    url = f"{request.url.scheme}://{request.url.netloc}/book/{salon_id}"
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


# ── PWA (установка на экран смартфона) ───────────────────────────────────────
_SW_JS = """
const CACHE = 'rumi-offline-v1';
const OFFLINE = '/offline';
self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.add(OFFLINE)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});
self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  // network-first: всегда свежее из сети; app-shell НЕ кэшируем — нет устаревших версий.
  e.respondWith(
    fetch(req).catch(() => (req.mode === 'navigate' ? caches.match(OFFLINE) : Response.error()))
  );
});
"""

_OFFLINE_HTML = """<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Нет сети — Руми</title></head>
<body style="font-family:system-ui,-apple-system,sans-serif;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0;background:#faf9fb;color:#1a1523">
<div style="text-align:center;padding:2rem">
<div style="font-size:1.6rem;font-weight:800;color:#c081b8">руми.</div>
<p style="color:#6b6577">Нет подключения к интернету.<br>Проверьте связь и попробуйте снова.</p>
<button onclick="location.reload()" style="background:#c081b8;color:#fff;border:none;border-radius:10px;padding:.6rem 1.2rem;font-size:1rem;cursor:pointer">Обновить</button>
</div></body></html>"""


@router.get("/manifest.webmanifest", include_in_schema=False)
async def pwa_manifest():
    import json
    from fastapi import Response
    manifest = {
        "name": "Руми — запись в салоны красоты",
        "short_name": "Руми",
        "description": "Онлайн-запись в салоны красоты и к мастерам",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "lang": "ru",
        "background_color": "#faf9fb",
        "theme_color": "#c081b8",
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/static/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    return Response(content=json.dumps(manifest, ensure_ascii=False),
                    media_type="application/manifest+json")


@router.get("/sw.js", include_in_schema=False)
async def pwa_service_worker():
    from fastapi import Response
    return Response(content=_SW_JS, media_type="application/javascript",
                    headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@router.get("/offline", response_class=HTMLResponse, include_in_schema=False)
async def pwa_offline():
    return HTMLResponse(content=_OFFLINE_HTML)


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Страница профиля."""
    from app.web.pages.profile import render_profile_page
    
    user = await get_current_user_from_cookie(request, db)
    return HTMLResponse(content=render_profile_page(user))


@router.get("/bookings", response_class=HTMLResponse)
async def bookings_page(
    request: Request, 
    db: AsyncSession = Depends(get_db)
):
    """Страница 'Мои записи'."""
    from app.web.pages.bookings import render_bookings_page
    
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login?redirect=/bookings", status_code=302)
    
    return HTMLResponse(content=await render_bookings_page(db, user))


@router.get("/favorites", response_class=HTMLResponse)
async def favorites_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Страница 'Избранное'."""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login?redirect=/favorites", status_code=302)
    from app.web.pages.favorites import render_favorites_page
    return HTMLResponse(content=await render_favorites_page(db, user))


@router.get("/business", response_class=HTMLResponse)
async def business_landing_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Страница «Для бизнеса» (лендинг)."""
    user = await get_current_user_from_cookie(request, db)
    return HTMLResponse(content=render_business_landing_page(user))


@router.get("/business/dashboard", response_class=HTMLResponse)
async def business_dashboard_page(
    request: Request,
    salon_id: int = None,
    db: AsyncSession = Depends(get_db)
):
    """Бизнес-панель с аналитикой."""
    from app.web.pages.business import render_business_dashboard
    from app.api.deps import get_user_primary_salon_id, get_salon_membership

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login?redirect=/business/dashboard", status_code=302)

    # salon_id из URL (явное переключение через свитчер) в приоритете; если его
    # нет — пробуем салон, запомненный в cookie с прошлого визита, и только
    # если он тоже недоступен — стандартную эвристику get_user_primary_salon_id.
    resolved_id = None
    if salon_id is not None:
        resolved_id = await get_user_primary_salon_id(db, user.id, salon_id)
    if resolved_id is None:
        last_salon_cookie = request.cookies.get("last_salon_id")
        if last_salon_cookie and last_salon_cookie.isdigit():
            resolved_id = await get_user_primary_salon_id(db, user.id, int(last_salon_cookie))
    if resolved_id is None:
        resolved_id = await get_user_primary_salon_id(db, user.id, None)

    if resolved_id is not None:
        salon = (await db.execute(select(Salon).where(Salon.id == resolved_id))).scalar_one_or_none()
        membership = await get_salon_membership(db, user.id, resolved_id)
        if salon and membership:
            response = HTMLResponse(content=await render_business_dashboard(db, user, salon, membership, request.query_params))
            response.set_cookie(
                key="last_salon_id",
                value=str(resolved_id),
                httponly=True,
                secure=settings.COOKIE_SECURE,
                max_age=365 * 24 * 60 * 60,
                samesite="lax",
                path="/",
            )
            return response

    master = (await db.execute(select(Master).where(Master.user_id == user.id, Master.is_active == True))).scalar_one_or_none()
    if master is not None:
        from app.web.pages.business.master_dashboard import render_master_business_dashboard
        salon = (await db.execute(select(Salon).where(Salon.id == master.salon_id))).scalar_one_or_none()
        if salon is not None:
            return HTMLResponse(content=await render_master_business_dashboard(db, user, salon, master, request.query_params))

    return RedirectResponse(url="/business/register-salon", status_code=302)


@router.get("/business/register-salon", response_class=HTMLResponse)
async def register_salon_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Анкета регистрации салона."""
    from app.web.pages.register_salon import render_register_salon_page

    user = await get_current_user_from_cookie(request, db)
    if not user or user.role.value != "business":
        return RedirectResponse(url="/login?redirect=/business/register-salon", status_code=302)
    return HTMLResponse(content=render_register_salon_page(user))


@router.get("/business/my-salon", response_class=HTMLResponse)
async def my_salon_page_redirect():
    """Редирект на панель с вкладкой редактирования."""
    return RedirectResponse(url="/business/dashboard?tab=edit", status_code=302)


@router.get("/business/clients/{client_id}", response_class=HTMLResponse)
async def client_card_page(
    client_id: int,
    request: Request,
    salon_id: int = None,
    db: AsyncSession = Depends(get_db)
):
    """Детальная карточка клиента."""
    from app.crm.tabs.client_card import render_client_card
    from app.api.deps import get_user_primary_salon_id, get_salon_membership

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url=f"/login?redirect=/business/clients/{client_id}", status_code=302)

    resolved_id = await get_user_primary_salon_id(db, user.id, salon_id)
    if resolved_id is None:
        return RedirectResponse(url="/business/register-salon", status_code=302)

    salon = (await db.execute(select(Salon).where(Salon.id == resolved_id))).scalar_one_or_none()
    membership = await get_salon_membership(db, user.id, resolved_id)
    if not salon or not membership:
        return RedirectResponse(url="/business/register-salon", status_code=302)

    return HTMLResponse(content=await render_client_card(db, salon, user, client_id))


@router.get("/master/dashboard", response_class=HTMLResponse)
async def master_dashboard_page_route():
    return RedirectResponse(url="/business/dashboard", status_code=302)


@router.get("/master/inventory", response_class=HTMLResponse)
async def master_inventory_page_route(request: Request, db: AsyncSession = Depends(get_db)):
    from app.web.pages.master.inventory import render_master_inventory
    from app.models.models import UserRole

    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login?redirect=/master/inventory", status_code=302)
    if user.role != UserRole.MASTER:
        return RedirectResponse(url="/", status_code=302)

    return HTMLResponse(content=await render_master_inventory(db, user))


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, db: AsyncSession = Depends(get_db)):
    from app.web.pages.admin_panel import render_admin_panel

    user = await get_current_user_from_cookie(request, db)
    if not user or user.role.value != "admin" or not user.is_active:
        return RedirectResponse(url="/login?redirect=/admin", status_code=302)

    return HTMLResponse(content=await render_admin_panel(db, user, request.query_params))


@router.get("/business/checkout", response_class=HTMLResponse)
async def business_checkout_page(request: Request, db: AsyncSession = Depends(get_db)):
    plan = request.query_params.get("plan", "business")
    user = await get_current_user_from_cookie(request, db)
    from app.web.pages.business_checkout import render_business_checkout_page
    return HTMLResponse(content=render_business_checkout_page(plan, user))


@router.get("/salons/{salon_id}/book", response_class=HTMLResponse)
async def book_service_page(salon_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url=f"/login?redirect=/salons/{salon_id}/book", status_code=302)
    
    result = await db.execute(select(Salon).where(Salon.id == salon_id))
    salon = result.scalar_one_or_none()
    if not salon:
        return HTMLResponse(content="<h1>Салон не найден</h1>", status_code=404)
    
    masters_result = await db.execute(select(Master).where(Master.salon_id == salon_id, Master.is_active == True))
    masters = masters_result.scalars().all()
    
    masters_options = ""
    for m in masters:
        user_res = await db.execute(select(User).where(User.id == m.user_id))
        master_user = user_res.scalar_one_or_none()
        name = master_user.full_name if master_user else "Мастер"
        masters_options += f'<option value="{m.id}">{name} — {e(m.specialization)}</option>'
    
    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Запись — {e(salon.name)} — руми</title>
    {get_base_styles()}
</head>
<body>
    {render_header("salons")}
    <div class="section-container" style="padding-top:2rem;max-width:500px;margin:0 auto">
        <h1 class="text-display" style="font-size:1.75rem;margin-bottom:0.5rem">Запись в {e(salon.name)}</h1>
        <p class="text-muted" style="margin-bottom:2rem">Выберите мастера и услугу</p>
        <form action="/api/v1/bookings" method="post">
            <input type="hidden" name="salon_id" value="{salon_id}">
            <div style="margin-bottom:1rem">
                <label style="display:block;font-weight:500;margin-bottom:0.5rem">Мастер</label>
                <select name="master_id" class="custom-select" required>
                    <option value="">Выберите мастера</option>
                    {masters_options}
                </select>
            </div>
            <div style="margin-bottom:1rem">
                <label style="display:block;font-weight:500;margin-bottom:0.5rem">Услуга</label>
                <select name="service_id" class="custom-select" required onchange="updatePriceAndTime(this)">
                    <option value="">Сначала выберите мастера</option>
                </select>
            </div>
            <div style="margin-bottom:1rem">
                <label style="display:block;font-weight:500;margin-bottom:0.5rem">Дата и время</label>
                <input type="datetime-local" name="start_time" style="width:100%;padding:0.75rem;border:1px solid var(--color-border);border-radius:0.5rem" required>
            </div>
            <button type="submit" class="btn-primary" style="width:100%">Записаться</button>
        </form>
    </div>
    
    <script>
        document.querySelector('select[name="master_id"]').addEventListener('change', async function() {{
            const masterId = this.value;
            const serviceSelect = document.querySelector('select[name="service_id"]');
            
            if (!masterId) {{
                serviceSelect.innerHTML = '<option value="">Сначала выберите мастера</option>';
                return;
            }}
            
            try {{
                const response = await fetch(`/api/v1/masters/${{masterId}}/services`);
                const services = await response.json();
                
                serviceSelect.innerHTML = '<option value="">Выберите услугу</option>';
                services.forEach(service => {{
                    serviceSelect.innerHTML += `<option value="${{service.id}}" data-price="${{service.price}}" data-duration="${{service.duration_minutes}}">${{e(service.name)}} — ${{service.price}} ₽ (${{service.duration_minutes}} мин)</option>`;
                }});
            }} catch (error) {{
                console.error('Ошибка загрузки услуг:', error);
            }}
        }});
        
        function updatePriceAndTime(select) {{
            const selectedOption = select.options[select.selectedIndex];
            if (selectedOption && selectedOption.dataset.price) {{
                console.log('Цена:', selectedOption.dataset.price);
            }}
        }}
    </script>
</body>
</html>"""
    return HTMLResponse(content=html)


def _alert(msg: str) -> str:
    if not msg:
        return ""
    return (
        '<div style="background:#FEE2E2;color:#991B1B;border:1px solid #FCA5A5;'
        'border-radius:0.5rem;padding:0.75rem 1rem;margin-bottom:1rem;font-size:0.875rem">'
        f'{msg}</div>'
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return HTMLResponse(content=render_login_page(request))


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return HTMLResponse(content=render_register_page(request))


@router.get("/logout", response_class=HTMLResponse)
async def logout_page():
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("access_token")
    return response


@router.get("/about", response_class=HTMLResponse)
async def about_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    return HTMLResponse(content=render_about_page(user))


# ── Нормативные документы ────────────────────────────────────────────────────
# Отдельные страницы, а не файлы: ч.2 ст.18.1 152-ФЗ требует свободного доступа
# к Политике, а на практике — текстом, доступным для копирования и поиска.
# Адреса /terms и /privacy выбраны не случайно: на них уже ссылалась страница
# подключения салона, и обе ссылки вели на 404.
@router.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    return HTMLResponse(content=render_legal_page("terms", user))


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    return HTMLResponse(content=render_legal_page("privacy", user))


@router.get("/consent", response_class=HTMLResponse)
async def consent_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    return HTMLResponse(content=render_legal_page("consent", user))


@router.get("/offer", response_class=HTMLResponse)
async def offer_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Оферта для клиентов — на неё ссылаются условия оплаты подписки."""
    user = await get_current_user_from_cookie(request, db)
    return HTMLResponse(content=render_legal_page("offer", user))


@router.get("/license", response_class=HTMLResponse)
async def license_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Лицензионная оферта для салонов и мастеров."""
    user = await get_current_user_from_cookie(request, db)
    return HTMLResponse(content=render_legal_page("license", user))


@router.get("/cookies", response_class=HTMLResponse)
async def cookies_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Политика cookie. Адрес /cookies зашит в саму Политику (п. 6.1)."""
    user = await get_current_user_from_cookie(request, db)
    return HTMLResponse(content=render_legal_page("cookies", user))


@router.get("/tariffs", response_class=HTMLResponse)
async def tariffs_page(request: Request, db: AsyncSession = Depends(get_db)):
    """«Тарифы и информация» — тарифы платформы, документы, инструкции по сайту."""
    user = await get_current_user_from_cookie(request, db)
    from app.web.pages.tariffs import render_tariffs_page
    return HTMLResponse(content=render_tariffs_page(user))


@router.get("/model", response_class=HTMLResponse)
async def model_landing_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    return HTMLResponse(content=render_model_landing_page(user))


@router.get("/model/join", response_class=HTMLResponse)
async def model_join_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login?redirect=/model/join", status_code=302)
    from app.models.models import ModelPhoto
    photos = (await db.execute(
        select(ModelPhoto).where(ModelPhoto.model_user_id == user.id).order_by(ModelPhoto.id)
    )).scalars().all()
    return HTMLResponse(content=render_model_join_page(user, photos=[{"id": p.id, "url": p.url} for p in photos]))


@router.get("/model/dashboard", response_class=HTMLResponse)
async def model_dashboard_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login?redirect=/model/dashboard", status_code=302)
    from app.web.pages.model_dashboard import render_model_dashboard
    return HTMLResponse(content=await render_model_dashboard(db, user))


@router.get("/book", response_class=HTMLResponse)
async def book_page(request: Request, db: AsyncSession = Depends(get_db)):
    params = dict(request.query_params)
    master_id = int(params.get("master_id", 0))
    service_id = int(params.get("service_id", 0))
    time_str = params.get("time", "")
    
    user = await get_current_user_from_cookie(request, db)
    
    master = (await db.execute(select(Master).where(Master.id == master_id))).scalar_one_or_none()
    service = (await db.execute(select(ServiceModel).where(ServiceModel.id == service_id))).scalar_one_or_none()
    
    if not master or not service:
        return HTMLResponse(content="<h1>Ошибка: мастер или услуга не найдены</h1>", status_code=404)
    
    master_user = (await db.execute(select(User).where(User.id == master.user_id))).scalar_one_or_none()
    master_name = master_user.full_name if master_user else "Мастер"
    salon = (await db.execute(select(Salon).where(Salon.id == master.salon_id))).scalar_one_or_none()
    salon_name = salon.name if salon else "Салон"
    
    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Подтверждение записи — руми</title>
    {get_base_styles()}
</head>
<body style="background:var(--color-surface-alt);min-height:100vh;display:flex;align-items:center;justify-content:center">
<div class="card" style="max-width:500px;width:100%;padding:2rem">
    <h2 style="margin-bottom:1.5rem">Подтверждение записи</h2>
    
    <div style="margin-bottom:1rem;padding:1rem;background:var(--color-surface-alt);border-radius:0.75rem">
        <p><strong>{ICON_BUILDING2} Салон:</strong> {e(salon_name)}</p>
        <p><strong>{ICON_SCISSORS} Мастер:</strong> {e(master_name)}</p>
        <p><strong>{ICON_SCISSORS} Услуга:</strong> {e(service.name)}</p>
        <p><strong>{ICON_CLOCK} Длительность:</strong> {service.duration_minutes} мин</p>
        <p><strong>{ICON_CALENDAR_DAYS} Время:</strong> {time_str.replace('T', ' ')}</p>
        <p><strong>{ICON_MONEY} Цена:</strong> <span style="font-size:1.25rem;font-weight:700;color:var(--color-primary)">{service.price} ₽</span></p>
    </div>
    
    <form action="/api/v1/bookings/confirm" method="post">
        <input type="hidden" name="master_id" value="{master_id}">
        <input type="hidden" name="service_id" value="{service_id}">
        <input type="hidden" name="start_time" value="{time_str}">
        <button type="submit" class="btn-primary" style="width:100%;padding:1rem;font-size:1rem">Подтвердить запись</button>
    </form>
    
    <a href="/salons/{master.salon_id}" style="display:block;text-align:center;margin-top:1rem;color:var(--color-muted);font-size:0.9rem">← Назад к салону</a>
</div>
</body>
</html>"""
    
    return HTMLResponse(content=html)


@router.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(
        "User-agent: *\n"
        "Disallow: /admin\n"
        "Disallow: /business/\n"
        "Disallow: /profile\n"
        "Disallow: /bookings\n"
        "Disallow: /favorites\n"
        "Disallow: /api/\n"
        "Allow: /\n"
        f"Sitemap: https://rrumi.ru/sitemap.xml\n"
    )


@router.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml(db: AsyncSession = Depends(get_db)):
    from fastapi.responses import Response

    static_pages = ["", "salons", "business", "model", "login", "register"]
    urls = [f"https://rrumi.ru/{p}" for p in static_pages]

    # В карту сайта — только реально публичные салоны: одобрены, опубликованы
    # владельцем и не скрыты (иначе ссылки вели бы на 404 карточки).
    from app.models.models import SalonModerationStatus
    salons = (await db.execute(select(Salon.id).where(
        Salon.is_active == True,  # noqa: E712
        Salon.moderation_status == SalonModerationStatus.APPROVED,
        Salon.published_at.isnot(None),
        access_clause(Salon),  # тариф: доступ открыт
        Salon.is_hidden == False,  # noqa: E712
    ))).scalars().all()
    urls += [f"https://rrumi.ru/salons/{sid}" for sid in salons]

    body = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{body}</urlset>"
    )
    return Response(content=xml, media_type="application/xml")


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    from app.web.pages.password_reset import render_forgot_password_page
    return HTMLResponse(content=render_forgot_password_page(request))


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request):
    from app.web.pages.password_reset import render_reset_password_page
    return HTMLResponse(content=render_reset_password_page(request))


@router.get("/{path:path}", response_class=HTMLResponse)
async def not_found_page(request: Request, path: str):
    return HTMLResponse(content=f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Страница не найдена — руми</title>
    {get_base_styles()}
    <style>
        .notfound {{
            text-align: center;
            padding: 6rem 2rem;
            min-height: 80vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background: linear-gradient(135deg, var(--page-gradient-1), var(--page-gradient-2));
        }}
        .notfound-code {{
            font-size: 8rem;
            font-weight: 900;
            background: linear-gradient(135deg, var(--color-primary), var(--color-accent));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            line-height: 1;
            margin-bottom: 1rem;
        }}
        .notfound h1 {{
            font-size: 2rem;
            color: var(--color-heading);
            margin-bottom: 0.75rem;
        }}
        .notfound p {{
            color: var(--color-muted);
            max-width: 28rem;
            margin: 0 auto 2rem;
            font-size: 1rem;
            line-height: 1.6;
        }}
        .notfound .path {{
            background: var(--color-surface);
            padding: 0.5rem 1rem;
            border-radius: 0.5rem;
            font-family: monospace;
            font-size: 0.9rem;
            color: var(--color-primary);
            border: 1px solid var(--color-border);
            margin-bottom: 1.5rem;
        }}
        .quick-links {{
            display: flex;
            gap: 1rem;
            flex-wrap: wrap;
            justify-content: center;
        }}
    </style>
</head>
<body>
    <div class="notfound">
        <div class="notfound-code">404</div>
        <h1>Страница не найдена</h1>
        <p>Такой страницы не существует. Возможно, она была удалена или вы набрали неправильный адрес.</p>
        <div class="path">/{path}</div>
        <div class="quick-links">
            <a href="/" class="btn-primary">{ICON_HOUSE} На главную</a>
            <a href="/salons" class="btn-outline">{ICON_SCISSORS} Найти салон</a>
            <a href="/model" class="btn-outline">{ICON_CAMERA} Стать моделью</a>
        </div>
    </div>
</body>
</html>""", status_code=404)