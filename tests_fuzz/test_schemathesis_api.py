"""Schemathesis по OpenAPI приложения, in-process через ASGI (решение 0016, п. 3).

Проверяем: НЕ 5xx и ответ соответствует схеме. 400/401/403/404/409/422 —
нормальные ответы на мусор. Прогон идёт тремя ролями: аноним, клиент, владелец
салона. Токены выдаются напрямую (create_access_token) на тех же пользователях,
которых заводит tests_fuzz/seed.py, — своих паролей не придумываем.

HTML-страницы (web_router, include_in_schema=False) в OpenAPI не попадают:
их фаззит test_props_text.py.

Падение в одной операции не прячет остальные: собираем все находки и падаем
один раз с полным списком; он же пишется в FUZZ_REPORT (артефакт CI).
"""
import asyncio
import json
import os
import pathlib

import httpx
import pytest
import schemathesis
from hypothesis import HealthCheck, Phase, given, seed, settings
from schemathesis.checks import not_a_server_error
from schemathesis.specs.openapi.checks import response_schema_conformance

from tests_fuzz.seed import seed as seed_data

EXAMPLES = int(os.environ.get("FUZZ_EXAMPLES", "12"))
SEED = int(os.environ.get("FUZZ_SEED", "20261027"))
REPORT = pathlib.Path(os.environ.get("FUZZ_REPORT", "fuzz-report"))

# ── Что НЕ дёргаем мусором (точные пары «метод + путь», без масок) ───────────
# Каждый пункт — с причиной. Список сверяется со схемой: если эндпоинт
# переименовали, а здесь остался старый путь, тест упадёт, а не молча «починится».
_PAY = "платёж/подписка: меняет деньги и состояние Т-Кассы, мусором не дёргаем"
EXCLUDED: dict[tuple[str, str], str] = {
    ("POST", "/api/v1/payments/business/init"): _PAY,
    ("POST", "/api/v1/payments/business/manual-charge"): _PAY,
    ("POST", "/api/v1/payments/business/change-plan"): _PAY,
    ("POST", "/api/v1/payments/business/enable-auto-renew"): _PAY,
    ("POST", "/api/v1/payments/business/cancel-auto-renew"): _PAY,
    ("POST", "/api/v1/payments/business/cancel-subscription"): _PAY,
    ("POST", "/api/v1/payments/business/custom-request"):
        "письмо в отдел продаж о корпоративном тарифе — это отправка почты",
    ("POST", "/api/v1/payments/model/init"): _PAY,
    ("POST", "/api/v1/payments/model/manual-charge"): _PAY,
    ("POST", "/api/v1/payments/model/cancel-auto-renew"): _PAY,
    ("POST", "/api/v1/payments/tkassa/notify"):
        "вебхук Т-Кассы: подпись проверяется, но обработчик двигает платежи и "
        "доступ; его покрывают test_refunds/test_billing_*",
    ("POST", "/api/v1/auth/register/send-code"):
        "отправка SMS/кода регистрации (деньги за SMS и лимит на номер)",
    ("POST", "/api/v1/auth/register/tg-start"): "выдаёт ссылку на Telegram-бота, ставит состояние в Redis",
    ("POST", "/api/v1/auth/register/max-start"): "то же для MAX",
    ("POST", "/api/v1/auth/reset-password"): "отправка письма/кода сброса пароля",
    ("POST", "/api/v1/users/me/email/send-code"): "отправка письма с кодом подтверждения",
    ("POST", "/api/v1/users/me/delete-form"):
        "удаление аккаунта: гасит цепочку карточка/салон/записи и рассылает отмены",
    ("POST", "/api/v1/business/staff/send-credentials"): "отправка учётных данных сотруднику почтой",
    ("GET", "/api/v1/auth/yandex/start"): "редирект на внешний OAuth Яндекса",
    ("GET", "/api/v1/auth/yandex/callback"): "обмен кода у Яндекса — исходящий запрос по построению",
    ("GET", "/api/v1/auth/vk/start"): "редирект на внешний VK ID",
    ("GET", "/api/v1/auth/vk/callback"): "обмен кода у VK — исходящий запрос по построению",
}
# Эндпоинтов, пишущих в журнал согласий на рекламу, в HTTP-схеме нет: их единственный
# вход — app/services/ad_consent.py из ботов. Если такой появится — внести сюда.

ROLES = ("anon", "client", "owner")


def _schema_dict(app) -> dict:
    """OpenAPI приложения с одной поправкой: start_time/end_time записи у нас —
    «настенное» время салона БЕЗ часового пояса (так хранятся, см. Booking), а
    схема FastAPI называет их date-time. Менять формат ответа ради фаззера
    нельзя — сломаются клиенты, — поэтому здесь снимаем только format."""
    import copy
    spec = copy.deepcopy(app.openapi())
    for comp in spec.get("components", {}).get("schemas", {}).values():
        for name in ("start_time", "end_time"):
            prop = comp.get("properties", {}).get(name)
            if prop and prop.get("format") == "date-time":
                prop.pop("format")
    return spec


def _operations(schema):
    """Все операции схемы минус EXCLUDED; заодно проверка, что список не устарел."""
    found = {}
    for res in schema.get_all_operations():
        op = res.ok()
        found[(op.method.upper(), op.path)] = op
    stale = sorted(set(EXCLUDED) - set(found))
    assert not stale, f"в EXCLUDED пути, которых нет в схеме: {stale}"
    return [op for key, op in sorted(found.items()) if key not in EXCLUDED]


def _to_httpx(kwargs: dict) -> dict:
    """as_transport_kwargs() даёт параметры requests; httpx называет часть иначе."""
    kw = dict(kwargs)
    kw.pop("timeout", None)
    if "data" in kw and isinstance(kw["data"], (bytes, str)):
        kw["content"] = kw.pop("data")
    # multipart: Schemathesis может дать число или None вместо содержимого части,
    # requests это глотает, httpx требует str/bytes/файл
    files = kw.get("files")
    if isinstance(files, dict):
        kw["files"] = {k: _coerce_part(v) for k, v in files.items()}
    elif isinstance(files, list):
        kw["files"] = [(k, _coerce_part(v)) for k, v in files]
    if isinstance(kw.get("data"), dict):
        kw["data"] = {k: v if isinstance(v, (str, bytes)) else json.dumps(v) for k, v in kw["data"].items()}
    return kw


def _coerce_part(value):
    if isinstance(value, tuple):
        return (value[0], _coerce_part(value[1]), *value[2:])
    if isinstance(value, (str, bytes)) or hasattr(value, "read"):
        return value
    return json.dumps(value)


@pytest.mark.parametrize("role", ROLES)
def test_api_never_5xx(role, db_session, no_outbound):
    from app.main import app
    from app.db import session as db_session_mod

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)   # ключ: один loop на весь прогон — пулы БД/Redis к нему привязаны
    try:
        tokens = loop.run_until_complete(seed_data(db_session))
        headers = {"Origin": "http://testserver"}
        if role != "anon":
            headers["Authorization"] = f"Bearer {tokens[role]}"

        schema = schemathesis.openapi.from_dict(_schema_dict(app))
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                   base_url="http://testserver")
        findings: list[dict] = []

        def send(case):
            kw = _to_httpx(case.as_transport_kwargs(base_url="http://testserver"))
            kw["headers"] = {**kw.get("headers", {}), **headers}
            req = client.build_request(**kw)
            req.read()   # multipart-тело — поток; без read() Schemathesis не может его прочитать
            return loop.run_until_complete(client.send(req))

        for op in _operations(schema):
            @seed(SEED)
            @settings(max_examples=EXAMPLES, deadline=None, database=None,
                      suppress_health_check=list(HealthCheck),
                      phases=[Phase.generate, Phase.shrink])
            @given(case=op.as_strategy())
            def one(case):
                resp = send(case)
                case.validate_response(
                    resp, checks=[not_a_server_error, response_schema_conformance]
                )

            try:
                one()
            except BaseException as exc:  # noqa: BLE001 — собираем все, не только первую
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                findings.append({"role": role, "operation": f"{op.method.upper()} {op.path}",
                                 "error": str(exc)[:1500]})

        loop.run_until_complete(client.aclose())
        loop.run_until_complete(db_session_mod.engine.dispose())
    finally:
        loop.close()
        asyncio.set_event_loop(None)

    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / f"schemathesis-{role}.json").write_text(
        json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8")
    assert not findings, (
        f"{len(findings)} находок ({role}), подробности в {REPORT}/schemathesis-{role}.json:\n"
        + "\n".join(f"  {f['operation']}: {f['error'].splitlines()[0]}" for f in findings)
    )
