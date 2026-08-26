# app/main.py

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from app.api.v1.endpoints import users
from app.api.v1.endpoints import bookings
from app.web.views import router as web_router
from app.api.v1.endpoints import master as master_endpoints

from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.core.limiter import limiter
from app.core.middleware import SecurityHeadersMiddleware, CSRFOriginMiddleware
from app.core.worker import close_arq_pool
from app.core.observability import setup_logging, init_sentry

# Мониторинг и логи (блок 05): настроить логи и включить трекинг ошибок
# (Sentry/GlitchTip активируется только при заданном SENTRY_DSN).
setup_logging()
init_sentry()

from app.api.v1.endpoints import auth
from app.api.v1.endpoints import guest
from app.api.v1.endpoints import business
from app.api.v1.endpoints import auth_web
from app.api.v1.endpoints import reviews
from app.api.v1.endpoints import services
from app.api.v1.endpoints import favorites

from app.api.v1.endpoints import admin
from app.api.v1.endpoints import staff
from app.api.v1.endpoints import salon_chains
from app.api.v1.endpoints import inventory
from app.api.v1.endpoints import payroll
from app.api.v1.endpoints import loyalty
from app.api.v1.endpoints import uploads
from app.api.v1.endpoints import auth_yandex
from app.api.v1.endpoints import auth_vk
from app.api.v1.endpoints import schedule as schedule_endpoints
from app.api.v1.endpoints import reports
from app.api.v1.endpoints import model_matching
from app.api.v1.endpoints import payments

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Фоновые задачи (ARQ): пул создаётся лениво при первом enqueue,
    # здесь закрываем его на shutdown
    await close_arq_pool()


app = FastAPI(
    title="Beauty Platform API",
    description="API для платформы красоты Руми",
    version="0.3.0",
    lifespan=lifespan,
)

# --- Rate limiting (slowapi) ---
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# --- Необработанные исключения ---
# Без этого пользователь на веб-странице видел голый текст "Internal Server
# Error" без единого стиля сайта (см. жалобу: сессия долго висела открытой
# в фоне, при возврате — токен протух, где-то в цепочке зависимостей это
# уронило запрос необработанным исключением). HTTPException(...) сюда не
# попадает — для него у FastAPI уже есть более специфичный дефолтный
# handler, так что осознанные "raise HTTPException(500, ...)" в коде
# по-прежнему отдают свой JSON как и раньше. Это именно страховка на
# случай ПОЛНОСТЬЮ неожиданного исключения.
import logging as _logging
_error_logger = _logging.getLogger("app.errors")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    _error_logger.exception(
        "Необработанное исключение: %s %s", request.method, request.url.path,
    )
    if settings.SENTRY_DSN:
        import sentry_sdk
        sentry_sdk.capture_exception(exc)

    if request.url.path.startswith("/api/"):
        return JSONResponse(status_code=500, content={"detail": "Внутренняя ошибка сервера"})

    from app.web.views import render_status_page
    from app.web.components.icons import ICON_REFRESH
    extra = (
        f'<button type="button" onclick="location.reload()" class="btn-primary" '
        f'style="margin-bottom:1.5rem;border:none;cursor:pointer">{ICON_REFRESH} Обновить страницу</button>'
    )
    html_content = render_status_page(
        500, "Что-то пошло не так",
        "Такое иногда случается — обычно помогает обновить страницу. "
        "Если ошибка повторяется, напишите нам в поддержку.",
        extra=extra,
    )
    return HTMLResponse(content=html_content, status_code=500)

# --- Middleware безопасности ---
# CORS: явный список origin'ов (FastAPI не закрывает это по умолчанию)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CSRFOriginMiddleware)

# 1. Статические файлы — ПЕРВЫМИ!
app.mount("/static", StaticFiles(directory="static"), name="static")

# Загруженные пользователями изображения (аватары, фото салонов) — отдельный
# каталог-volume, не запекается в образ и переживает деплой
import os as _os
_os.makedirs(settings.UPLOADS_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.UPLOADS_DIR), name="uploads")

# 2. API-роутеры — ДОЛЖНЫ БЫТЬ ДО ВЕБ-РОУТЕРА
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(auth_web.router, prefix="/api/v1/auth", tags=["auth-web"])
app.include_router(users.router, prefix="/api/v1/users", tags=["users"])
app.include_router(bookings.router, prefix="/api/v1/bookings", tags=["bookings"])
app.include_router(business.router, prefix="/api/v1/business", tags=["business"])
app.include_router(master_endpoints.router, prefix="/api/v1/master", tags=["master"])
app.include_router(reviews.router, prefix="/api/v1", tags=["reviews"])
app.include_router(services.router, prefix="/api/v1", tags=["services"])
app.include_router(favorites.router, prefix="/api/v1", tags=["favorites"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
app.include_router(staff.router, prefix="/api/v1/business/staff", tags=["staff"])
app.include_router(salon_chains.router, prefix="/api/v1/business/chain", tags=["salon-chains"])
app.include_router(inventory.router, prefix="/api/v1/inventory", tags=["inventory"])
app.include_router(payroll.router, prefix="/api/v1/payroll", tags=["payroll"])
app.include_router(uploads.router, prefix="/api/v1/upload", tags=["uploads"])
app.include_router(auth_yandex.router, prefix="/api/v1/auth", tags=["auth-yandex"])
app.include_router(auth_vk.router, prefix="/api/v1/auth", tags=["auth-vk"])
app.include_router(loyalty.router, prefix="/api/v1/loyalty", tags=["loyalty"])
app.include_router(schedule_endpoints.router, prefix="/api/v1/schedule", tags=["schedule"])
app.include_router(reports.router, prefix="/api/v1/reports", tags=["reports"])
app.include_router(guest.router, prefix="/api/v1/guest", tags=["guest"])
app.include_router(model_matching.router, prefix="/api/v1/model-matching", tags=["model-matching"])
app.include_router(payments.router, prefix="/api/v1/payments", tags=["payments"])

# Healthcheck — регистрируем ДО веб-роутера, иначе его перехватывает
# catch-all страниц (`/{path:path}`) и /health отдаёт 404.
@app.get("/health", include_in_schema=False)
async def health_check():
    return {"status": "ok"}


# 3. Веб-роутер (страницы) — ПОСЛЕ API
app.include_router(web_router, include_in_schema=False)