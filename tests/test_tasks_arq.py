# tests/test_tasks_arq.py
"""Фоновые задачи (блок 06): ретраи с backoff, дедуп вебхуков, отбраковка."""
import asyncio

import pytest
from arq import create_pool
from arq.worker import Worker

import app.tasks as tasks
from app.core.worker import REDIS_SETTINGS

QUEUE = "test_queue_12"


@pytest.fixture()
async def arq_pool():
    pool = await create_pool(REDIS_SETTINGS)
    yield pool
    await pool.aclose()


def _worker(functions):
    return Worker(
        functions=functions,
        redis_settings=REDIS_SETTINGS,
        queue_name=QUEUE,
        max_tries=5,
        poll_delay=0.1,
        handle_signals=False,
    )


async def test_send_sms_retries_on_transient_failures(arq_pool, monkeypatch):
    calls = {"n": 0}

    async def flaky(phone, message):
        calls["n"] += 1
        if calls["n"] < 3:
            raise tasks.TransientTaskError("провайдер 502")

    monkeypatch.setattr(tasks, "_send_via_provider", flaky)
    monkeypatch.setattr(tasks, "RETRY_BASE_DELAY", 0)  # без задержек в тестах

    job = await arq_pool.enqueue_job("send_sms", "+79991112233", "тест", _queue_name=QUEUE)
    worker = _worker([tasks.send_sms])
    wtask = asyncio.create_task(worker.async_run())
    try:
        result = await job.result(timeout=15)
    finally:
        await worker.close()
        wtask.cancel()

    assert result == "sent"
    assert calls["n"] == 3
    assert worker.jobs_retried == 2


async def test_webhook_dedup_by_job_id(arq_pool):
    payload = {"OrderId": "ord-1", "Status": "CONFIRMED"}
    j1 = await arq_pool.enqueue_job(
        "process_payment_webhook", payload,
        _job_id="tkassa:ord-1:CONFIRMED", _queue_name=QUEUE,
    )
    j2 = await arq_pool.enqueue_job(
        "process_payment_webhook", payload,
        _job_id="tkassa:ord-1:CONFIRMED", _queue_name=QUEUE,
    )
    assert j1 is not None
    assert j2 is None  # дубль доставки отсечён до выполнения


async def test_webhook_without_order_id_rejected_without_retries(arq_pool):
    job = await arq_pool.enqueue_job(
        "process_payment_webhook", {"Status": "CONFIRMED"}, _queue_name=QUEUE
    )
    worker = _worker([tasks.process_payment_webhook])
    wtask = asyncio.create_task(worker.async_run())
    try:
        result = await job.result(timeout=15)
    finally:
        await worker.close()
        wtask.cancel()

    assert result == "rejected"
    assert worker.jobs_retried == 0


async def test_send_email_retries_on_transient(arq_pool, monkeypatch):
    """Email-задача: временные сбои SMTP ретраятся, как у SMS/TG."""
    calls = {"n": 0}

    async def flaky(to, subject, body, html=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise tasks.TransientTaskError("SMTP 421")

    monkeypatch.setattr(tasks, "_send_via_smtp", flaky)
    monkeypatch.setattr(tasks, "RETRY_BASE_DELAY", 0)

    job = await arq_pool.enqueue_job(
        "send_email", "user@example.com", "Тест", "тело", _queue_name=QUEUE
    )
    worker = _worker([tasks.send_email])
    wtask = asyncio.create_task(worker.async_run())
    try:
        result = await job.result(timeout=15)
    finally:
        await worker.close()
        wtask.cancel()

    assert result == "sent"
    assert calls["n"] == 3
