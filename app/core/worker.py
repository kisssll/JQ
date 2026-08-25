# app/core/worker.py
"""ARQ: настройки воркера и пул для постановки задач (блок 06).

Очередь живёт в том же Redis, что и rate limiting (settings.REDIS_URL).
Воркер — отдельный процесс:
    arq app.core.worker.WorkerSettings          # запуск
    arq --check app.core.worker.WorkerSettings  # health check (compose)
В проде — сервис arq-worker в docker-compose.prod.yml.

Постановка задачи из веб-процесса:
    pool = await get_arq_pool()
    await pool.enqueue_job("send_sms", phone, message)
"""
from __future__ import annotations

from arq import create_pool, cron
from arq.connections import ArqRedis, RedisSettings

from app.core.config import settings
from app.tasks import (
    charge_due_subscriptions, finalize_tkassa_verification, process_payment_webhook,
    reconcile_refunds,
    send_booking_reminder, send_email, send_evening_deals_blast, send_max_message, send_sms, send_tg_message,
    subscription_reminders,
)

REDIS_SETTINGS = RedisSettings.from_dsn(settings.REDIS_URL)

# ── Пул для enqueue из веб-процесса (лениво, один на процесс) ────

_pool: ArqRedis | None = None


async def get_arq_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(REDIS_SETTINGS)
    return _pool


async def close_arq_pool() -> None:
    """Закрытие пула на shutdown приложения (см. app/main.py)."""
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


# ── Настройки воркера ────────────────────────────────────────────


async def _on_startup(ctx: dict) -> None:
    # Мониторинг и логи (блок 05) для процесса воркера: те же логи + трекинг
    # ошибок фоновых задач в GlitchTip/Sentry (при заданном SENTRY_DSN).
    from app.core.observability import init_sentry, setup_logging

    setup_logging()
    init_sentry()


class WorkerSettings:
    functions = [
        send_sms, send_tg_message, send_max_message, send_booking_reminder, send_email,
        subscription_reminders,
        process_payment_webhook, send_evening_deals_blast,
        finalize_tkassa_verification, charge_due_subscriptions,
        reconcile_refunds,
    ]
    # Ежедневная рассылка «вечерних окон со скидкой» в 18:00 по Томску (UTC+7).
    # arq считает cron по локальному времени процесса; контейнер воркера в UTC,
    # поэтому 11:00 UTC = 18:00 Томск. (Если TZ контейнера сменят — поправить.)
    # Автосписания подписок — в 06:00 UTC (13:00 Томск), отдельно от рассылки.
    # Скрытие неоплаченных салонов — в 06:30, через полчаса после автосписаний,
    # чтобы успешное продление не «наткнулось» на скрытие в ту же ночь.
    cron_jobs = [
        cron(send_evening_deals_blast, hour={11}, minute={0}, run_at_startup=False),
        cron(charge_due_subscriptions, hour={6}, minute={0}, run_at_startup=False),
        # Напоминания по подписке — раз в сутки, 09:00 Томск (02:00 UTC)
        cron(subscription_reminders, hour={2}, minute={0}, run_at_startup=False),
        # Сверка возвратов с кассой — в 03:00 UTC, после напоминаний и до
        # автосписаний: если возврат заметили сверкой, автопродление уже
        # снято и лишнего списания в ту же ночь не будет.
        cron(reconcile_refunds, hour={3}, minute={0}, run_at_startup=False),
    ]
    redis_settings = REDIS_SETTINGS
    on_startup = _on_startup
    max_tries = 5            # потолок для Retry из задач (см. app/tasks.py)
    job_timeout = 60         # сек на одну задачу
    keep_result = 3600       # результат храним час (отладка/идемпотентность)
    health_check_interval = 30  # воркер пишет health-ключ в Redis для --check
