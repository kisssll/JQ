# app/main.py

from contextlib import asynccontextmanager

from geopy.distance import geodesic
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from app.api.v1.endpoints import users
from app.api.v1.endpoints import bookings
from app.web.views import router as web_router
from app.api.v1.endpoints import master as master_endpoints

from fastapi.staticfiles import StaticFiles
from app.db.session import get_db
from app.core.config import settings
from app.core.limiter import limiter
from app.core.middleware import SecurityHeadersMiddleware, CSRFOriginMiddleware
from app.core.worker import close_arq_pool
from app.core.observability import setup_logging, init_sentry

# Мониторинг и логи (блок 05): настроить логи и включить трекинг ошибок
# (Sentry/GlitchTip активируется только при заданном SENTRY_DSN).
setup_logging()
init_sentry()

from app.models.models import Salon, Master, User, Service, SalonModerationStatus

# Публичный салон = активен И заявка одобрена (pending/rejected не показываем
# и не даём записаться — модерация регистрации бизнеса) И опубликован владельцем
# (published_at не NULL — одобрение само по себе больше не выводит в каталог)
# И не скрыт владельцем.
_PUBLIC_SALON = (
    (Salon.is_active == True)  # noqa: E712
    & (Salon.moderation_status == SalonModerationStatus.APPROVED)
    & (Salon.published_at.isnot(None))
    & (Salon.is_hidden == False)  # noqa: E712
)
from app.schemas.salon import SalonResponse, SalonWithDistance
from app.schemas.master import MasterResponse, ServiceResponse
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

# StaticFiles определяет Content-Type через mimetypes, а тот читает базу
# системы. В образе она беднее, чем на машине разработчика: .webp уезжал
# клиенту как application/octet-stream. Браузеры такое обычно распознают по
# содержимому, но полагаться на угадывание не стоит — регистрируем явно.
import mimetypes as _mimetypes

for _ext, _type in ((".webp", "image/webp"), (".avif", "image/avif"),
                    (".svg", "image/svg+xml")):
    _mimetypes.add_type(_type, _ext)

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


@app.get("/api/v1/salons", response_model=List[SalonResponse])
async def get_salons(db: AsyncSession = Depends(get_db)):
    """Получить список всех салонов"""
    result = await db.execute(select(Salon).where(_PUBLIC_SALON))
    salons = result.scalars().all()
    return salons

@app.get("/api/v1/salons/nearby", response_model=List[SalonWithDistance])
async def get_nearby_salons(
    lat: float,
    lon: float,
    radius: float = 5.0,
    db: AsyncSession = Depends(get_db)
):
    """Получить салоны в радиусе N километров от указанных координат"""
    
    result = await db.execute(select(Salon).where(_PUBLIC_SALON))
    salons = result.scalars().all()
    
    user_location = (lat, lon)
    nearby_salons = []
    
    for salon in salons:
        salon_location = (salon.latitude, salon.longitude)
        distance = geodesic(user_location, salon_location).kilometers
        
        if distance <= radius:
            salon.distance_km = round(distance, 2)
            nearby_salons.append(salon)
    
    nearby_salons.sort(key=lambda s: s.distance_km)
    return nearby_salons

@app.get("/api/v1/salons/{salon_id}", response_model=SalonResponse)
async def get_salon(salon_id: int, db: AsyncSession = Depends(get_db)):
    """Получить информацию о конкретном салоне"""
    result = await db.execute(select(Salon).where(Salon.id == salon_id, _PUBLIC_SALON))
    salon = result.scalar_one_or_none()
    if not salon:
        raise HTTPException(status_code=404, detail="Салон не найден")
    return salon

@app.get("/api/v1/masters", response_model=List[MasterResponse])
async def get_masters(db: AsyncSession = Depends(get_db)):
    """Получить список всех мастеров"""
    result = await db.execute(
        select(Master)
        .where(Master.is_active == True)
        .order_by(Master.rating.desc())
    )
    masters = result.scalars().all()
    
    for master in masters:
        user_result = await db.execute(select(User).where(User.id == master.user_id))
        master.user = user_result.scalar_one_or_none()
        
        services_result = await db.execute(
            select(Service).where(Service.master_id == master.id)
        )
        master.services = services_result.scalars().all()
    
    return masters

@app.get("/api/v1/masters/{master_id}", response_model=MasterResponse)
async def get_master(master_id: int, db: AsyncSession = Depends(get_db)):
    """Получить информацию о конкретном мастере"""
    result = await db.execute(select(Master).where(Master.id == master_id))
    master = result.scalar_one_or_none()
    if not master:
        raise HTTPException(status_code=404, detail="Мастер не найден")
    
    user_result = await db.execute(select(User).where(User.id == master.user_id))
    master.user = user_result.scalar_one_or_none()
    
    services_result = await db.execute(
        select(Service).where(Service.master_id == master.id)
    )
    master.services = services_result.scalars().all()
    
    return master