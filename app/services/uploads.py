# app/services/uploads.py
"""Загрузка изображений (аватары, фото салона) — задача 1 от команды.

Безопасность (загрузка файлов — классическая дыра, поэтому строго):
- тип проверяется по СОДЕРЖИМОМУ (Pillow открывает и валидирует), не по
  расширению и не по Content-Type из запроса — их контролирует атакующий;
- файл ПЕРЕСОХРАНЯЕТСЯ: decode → resize → encode в JPEG. Это уничтожает
  всё, что можно спрятать в метаданных/EXIF/полиглот-файле — на диск
  попадают только наши собственные пиксели;
- имя файла — uuid4, от пользователя не берётся ни байта пути;
- лимит размера читается до обработки, чтобы не декодировать гигабайты.

Хранилище: локальный каталог settings.UPLOADS_DIR (volume в compose).
ВРЕМЕННО до S3 Timeweb — интерфейс сводится к _store(), при переезде
меняется только он.
"""
import io
import uuid
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from app.core.config import settings

# Регистрирует HEIF/HEIC-декодер в Pillow (формат по умолчанию для фото с
# iPhone) — без этого Image.open() на таком файле кидает
# UnidentifiedImageError, хотя файл абсолютно валиден.
register_heif_opener()

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 МБ до обработки
JPEG_QUALITY = 85

# Максимальная сторона после ресайза по назначению
MAX_SIDE = {"avatars": 512, "salons": 1600, "masters": 1600, "reviews": 1600, "models": 1200}

# Ленивый boto3-клиент S3-режима (создаётся при первой заливке; в локальном
# режиме — тесты/локалка — boto3 не импортируется вовсе).
_s3_client = None


class UploadError(ValueError):
    """Файл не подходит: не изображение, повреждён или слишком большой."""


def process_image(data: bytes, kind: str) -> bytes:
    """Валидирует и пересохраняет картинку в чистый JPEG. Кидает UploadError."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadError("Файл больше 5 МБ")
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()  # структурная проверка формата
        img = Image.open(io.BytesIO(data))  # verify() портит объект — открываем заново
        # Телефон часто пишет пиксели «как снял сенсор» + EXIF-тег поворота,
        # а не поворачивает саму картинку. exif_transpose поворачивает пиксели
        # по этому тегу — ДО convert(), который EXIF всё равно стирает вместе
        # с остальными метаданными (так и задумано — не оставлять чужие данные
        # в файле), иначе тег терялся и фото оставалось повёрнутым как есть.
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")  # убирает альфу/палитры
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise UploadError("Файл не является изображением") from e

    max_side = MAX_SIDE.get(kind, 1600)
    img.thumbnail((max_side, max_side))  # пропорционально, только уменьшение

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return out.getvalue()


def _s3_enabled() -> bool:
    """S3-режим включён, когда задан публичный бакет фото."""
    return bool(settings.S3_MEDIA_BUCKET)


def _s3():
    """Ленивый boto3-клиент (импорт тоже ленивый — локальному режиму не нужен)."""
    global _s3_client
    if _s3_client is None:
        import boto3
        _s3_client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
        )
    return _s3_client


def _media_key(kind: str, name: str) -> str:
    """Ключ объекта в бакете: <prefix>/<kind>/<name> (prefix — окружение)."""
    prefix = settings.S3_MEDIA_PREFIX.strip("/")
    return "/".join(p for p in (prefix, kind, name) if p)


def _public_url(key: str) -> str:
    return f"{settings.S3_PUBLIC_URL_BASE.rstrip('/')}/{key}"


def _store(content: bytes, kind: str) -> str:
    """Кладёт готовый JPEG в хранилище, возвращает публичный URL.

    S3-режим (задан S3_MEDIA_BUCKET): грузим в публичный бакет, в БД — полный
    S3-URL. Иначе — локальный volume (fallback: тесты/локалка).
    """
    name = f"{uuid.uuid4()}.jpg"
    if _s3_enabled():
        key = _media_key(kind, name)
        _s3().put_object(
            Bucket=settings.S3_MEDIA_BUCKET, Key=key, Body=content,
            ContentType="image/jpeg",
        )
        return _public_url(key)
    directory = Path(settings.UPLOADS_DIR) / kind
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_bytes(content)
    return f"/uploads/{kind}/{name}"


async def save_image(file: UploadFile, kind: str) -> str:
    """Полный цикл: прочитать (с лимитом), обеззаразить, сохранить. → URL."""
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    return _store(process_image(data, kind), kind)


def delete_stored(url: str) -> None:
    """Удаляет файл по нашему URL (best-effort: файла может уже не быть).

    Понимает оба вида: полный S3-URL (публичный бакет) и локальный
    /uploads/<kind>/<uuid>.jpg — так работает и в переходный период. Путь/ключ
    берётся только из валидированного хвоста, произвольные пути не пролезают.
    """
    if not url:
        return
    base = settings.S3_PUBLIC_URL_BASE.rstrip("/")
    if _s3_enabled() and base and url.startswith(base + "/"):
        key = url[len(base) + 1:]
        try:
            _s3().delete_object(Bucket=settings.S3_MEDIA_BUCKET, Key=key)
        except Exception:
            pass
        return
    try:
        parts = Path(url).parts  # ('/', 'uploads', kind, name)
        if len(parts) == 4 and parts[1] == "uploads":
            target = Path(settings.UPLOADS_DIR) / parts[2] / parts[3]
            target.unlink(missing_ok=True)
    except OSError:
        pass
