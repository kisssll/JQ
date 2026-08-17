# app/scripts/migrate_uploads_to_s3.py
"""Одноразовый перенос загруженных фото с локального volume в S3.

Копирует файлы /uploads/<kind>/<file> в публичный бакет (ключ
<prefix>/<kind>/<file>) и переписывает URL в БД на публичный S3-URL.
Идемпотентно: значения, не начинающиеся с /uploads/, пропускаются — повторный
запуск безопасен, уже перенесённые не трогает.

Запуск (в контейнере с volume фото + доступом к БД):
    docker exec rumi-<env>-app python -m app.scripts.migrate_uploads_to_s3
Требует в .env: S3_MEDIA_BUCKET / S3_MEDIA_PREFIX / S3_PUBLIC_URL_BASE +
S3_ENDPOINT / S3_ACCESS_KEY / S3_SECRET_KEY.
"""
import asyncio
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.models import User, Salon, Master, SalonPhoto, ReviewPhoto, MasterPhoto
from app.services.uploads import _media_key, _public_url, _s3, _s3_enabled

# (модель, имя поля) для одиночных nullable-URL полей
_SINGLE = [(User, "avatar_url"), (User, "model_photo_url"),
           (Salon, "logo_url"), (Master, "photo_url")]
# таблицы фото с обязательным полем url
_PHOTO_TABLES = (SalonPhoto, ReviewPhoto, MasterPhoto)


def _migrate_url(url: str | None) -> str | None:
    """Локальный /uploads/<kind>/<name> → S3. Возвращает новый URL, либо None
    (не /uploads/ или файла нет на диске — не трогаем)."""
    if not url or not url.startswith("/uploads/"):
        return None
    parts = Path(url).parts  # ('/', 'uploads', kind, name)
    if len(parts) != 4:
        return None
    kind, name = parts[2], parts[3]
    local = Path(settings.UPLOADS_DIR) / kind / name
    if not local.exists():
        print(f"  ! файл отсутствует, URL оставлен: {url}")
        return None
    key = _media_key(kind, name)
    _s3().put_object(Bucket=settings.S3_MEDIA_BUCKET, Key=key,
                     Body=local.read_bytes(), ContentType="image/jpeg")
    return _public_url(key)


async def main() -> None:
    if not _s3_enabled():
        raise SystemExit("S3_MEDIA_BUCKET не задан — нечего переносить в S3")
    moved = 0
    async with AsyncSessionLocal() as db:
        for model, field in _SINGLE:
            for row in (await db.execute(select(model))).scalars().all():
                new = _migrate_url(getattr(row, field))
                if new:
                    setattr(row, field, new)
                    moved += 1
        for model in _PHOTO_TABLES:
            for row in (await db.execute(select(model))).scalars().all():
                new = _migrate_url(row.url)
                if new:
                    row.url = new
                    moved += 1
        await db.commit()
    print(f"[migrate] перенесено URL в S3: {moved}")


if __name__ == "__main__":
    asyncio.run(main())
