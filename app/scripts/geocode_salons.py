# app/scripts/geocode_salons.py
"""Разовый бэкфилл координат для салонов, созданных ДО подключения
геокодера — у них до сих пор захардкоженные координаты центра Москвы
(55.7558, 37.6173), из-за чего сортировка «рядом со мной» на /salons для них
бессмысленна. Находит адрес → пишет реальные latitude/longitude через
HTTP Геокодер Яндекса (тот же ключ YANDEX_MAPS_API_KEY).

Использование:
    python -m app.scripts.geocode_salons [--dry-run]

Безопасно перезапускать: трогает только салоны с координатами ровно
(55.7558, 37.6173) — уже геокодированные (через новую форму) не задевает.
"""
import argparse
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import engine
from app.core.config import settings
from app.models.models import Salon
from app.services.geocoding_service import geocode_address, GeocodingError

_OLD_DEFAULT_LAT = 55.7558
_OLD_DEFAULT_LON = 37.6173


async def _run(dry_run: bool) -> None:
    if not settings.YANDEX_MAPS_API_KEY:
        print("Ошибка: YANDEX_MAPS_API_KEY не задан в .env — нечем геокодировать.", file=sys.stderr)
        sys.exit(1)

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as db:
        salons = (await db.execute(
            select(Salon).where(Salon.latitude == _OLD_DEFAULT_LAT, Salon.longitude == _OLD_DEFAULT_LON)
        )).scalars().all()

        if not salons:
            print("Салонов с дефолтными координатами не найдено — бэкфилл не нужен.")
            return

        print(f"Найдено {len(salons)} салон(ов) с дефолтными координатами Москвы.")
        updated, skipped = 0, 0

        for salon in salons:
            if not salon.address or not salon.address.strip():
                print(f"  #{salon.id} «{salon.name}» — пустой адрес, пропускаю.")
                skipped += 1
                continue

            try:
                result = await geocode_address(salon.address)
            except GeocodingError as e:
                print(f"  #{salon.id} «{salon.name}» ({salon.address!r}) — ошибка геокодера: {e}")
                skipped += 1
                await asyncio.sleep(0.3)
                continue

            if result is None:
                print(f"  #{salon.id} «{salon.name}» ({salon.address!r}) — адрес не распознан, пропускаю.")
                skipped += 1
                await asyncio.sleep(0.3)
                continue

            lat, lon = result
            print(f"  #{salon.id} «{salon.name}» ({salon.address!r}) → {lat:.5f}, {lon:.5f}")
            if not dry_run:
                salon.latitude = lat
                salon.longitude = lon
            updated += 1
            await asyncio.sleep(0.3)  # без нужды не долбим геокодер пачкой

        if not dry_run:
            await db.commit()

        print(f"\nГотово: обновлено {updated}, пропущено {skipped}"
              f"{' (--dry-run, в БД ничего не записано)' if dry_run else ''}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Пересчитать координаты салонов с дефолтной точкой (Москва)")
    parser.add_argument("--dry-run", action="store_true", help="Только показать, что будет сделано, без записи в БД")
    args = parser.parse_args()
    asyncio.run(_run(args.dry_run))


if __name__ == "__main__":
    main()
