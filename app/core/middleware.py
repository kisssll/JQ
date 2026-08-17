# app/core/middleware.py
"""Серверные middleware: security-заголовки и защита от CSRF.

CSRF (бриф 3.3): веб-слой аутентифицируется cookie `access_token`, поэтому
для меняющих состояние запросов проверяем источник. Двойная защита:
  1) cookie ставится с SameSite=Lax (браузер не шлёт её на cross-site POST);
  2) этот middleware дополнительно сверяет заголовок Origin/Referer с хостом —
     блокирует подделанные запросы единообразно для всех *_web форм, не требуя
     прятать токен в каждую форму.
JSON-API использует Authorization: Bearer (без ambient cookie) — для него CSRF
неприменим, такие запросы не блокируем.
"""
from __future__ import annotations

from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _img_src_extra() -> str:
    """Доп. хосты для img-src сверх 'self' — публичный S3 с фото (двойной режим
    uploads). Когда S3 не настроен (локалка/тесты) фото лежат под /uploads = 'self',
    список пуст и CSP остаётся строгим. При включённом S3 картинки грузятся с
    внешнего хоста — без него браузер режет их (img-src), curl это не ловит."""
    hosts: list[str] = []
    for raw in (settings.S3_PUBLIC_URL_BASE, settings.S3_ENDPOINT):
        if not raw:
            continue
        p = urlparse(raw)
        if p.scheme and p.netloc:
            origin = f"{p.scheme}://{p.netloc}"
            if origin not in hosts:
                hosts.append(origin)
    return (" " + " ".join(hosts)) if hosts else ""


# CSP собираем один раз на старте: img-src = 'self' data: + публичный S3 (если задан).
_CSP = (
    f"default-src 'self'; img-src 'self' data:{_img_src_extra()}; "
    "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
    "frame-ancestors 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault("Permissions-Policy", "geolocation=(self), microphone=(), camera=()")
        # CSP базовый — inline-стили в шаблонах разрешаем, скрипты только со своего origin;
        # img-src расширяется публичным S3-хостом, когда фото хранятся в бакете
        headers.setdefault("Content-Security-Policy", _CSP)
        if settings.ENVIRONMENT == "production":
            headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


class CSRFOriginMiddleware(BaseHTTPMiddleware):
    """Сверяет Origin/Referer для cookie-аутентифицированных мутаций."""

    def __init__(self, app):
        super().__init__(app)
        # Разрешённые хосты: из CORS-списка
        self._allowed_hosts = {
            urlparse(o).netloc for o in settings.CORS_ORIGINS if o
        }

    def _host_allowed(self, value: str, request_host: str) -> bool:
        host = urlparse(value).netloc
        if not host:
            return False
        return host == request_host or host in self._allowed_hosts

    async def dispatch(self, request: Request, call_next):
        if request.method in UNSAFE_METHODS and request.cookies.get("access_token"):
            request_host = request.url.netloc
            origin = request.headers.get("origin")
            referer = request.headers.get("referer")

            if origin is not None:
                ok = self._host_allowed(origin, request_host)
            elif referer is not None:
                ok = self._host_allowed(referer, request_host)
            else:
                # Нет ни Origin, ни Referer у изменяющего запроса с cookie — отклоняем
                ok = False

            if not ok:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF: недопустимый источник запроса"},
                )

        return await call_next(request)
