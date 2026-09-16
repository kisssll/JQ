# app/jobs/ask_evening_deals_consent.py
"""Разовая рассылка вопроса о согласии на рекламную подборку вечерних окон.

Запускается ВРУЧНУЮ и один раз, не по расписанию:

    docker exec rumi-staging-app python -m app.jobs.ask_evening_deals_consent          # показать, кому уйдёт
    docker exec rumi-staging-app python -m app.jobs.ask_evening_deals_consent --send   # отправить

По умолчанию ничего не отправляет, только показывает список. Отправленное из
чужого мессенджера не отзовёшь — поэтому сначала смотрим глазами, потом
отправляем, и сначала на стейдже.

Спрашиваем тех, кому подборка приходила до перехода на согласие: у кого есть
канал, кто не гость, кого ещё не спрашивали и кто ещё не согласился. Повторный
запуск безопасен: уже спрошенных задача пропускает сама.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter

from sqlalchemy import select


async def _eligible():
    from app.db.session import AsyncSessionLocal
    from app.models.models import User
    from app.services import ad_consent
    from app.services.notify_channel import has_channel_clause, resolve

    async with AsyncSessionLocal() as db:
        users = (await db.execute(
            select(User).where(has_channel_clause(), User.is_guest.is_(False))
        )).scalars().all()
        picked = []
        for user in users:
            if ad_consent.was_asked(user) or ad_consent.is_consented(user):
                continue
            channel, address = resolve(user)
            if address is None:
                continue
            picked.append((user.id, channel.value))
        return picked


async def main(send: bool) -> None:
    picked = await _eligible()
    by_channel = Counter(channel for _, channel in picked)
    print(f"Спросим: {len(picked)} чел. — " +
          (", ".join(f"{ch}: {n}" for ch, n in sorted(by_channel.items())) or "никого"))

    if not send:
        print("Ничего не отправлено. Для отправки: --send")
        return

    from app.core.worker import get_arq_pool

    pool = await get_arq_pool()
    for user_id, _ in picked:
        # _job_id делает постановку идемпотентной: двойной запуск скрипта в
        # одну минуту не поставит вопрос одному человеку дважды.
        await pool.enqueue_job("ask_evening_deals_consent", user_id,
                               _job_id=f"ask-evening-deals-consent-{user_id}")
    print(f"Поставлено в очередь: {len(picked)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--send", action="store_true", help="действительно отправить")
    asyncio.run(main(parser.parse_args().send))
