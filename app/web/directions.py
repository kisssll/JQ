"""Переход между двумя публичными хостами одной среды."""
import hashlib
import json
import re
import secrets
import time
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse

from app.core.config import settings
from app.core.limiter import get_redis
from app.services.web_session import revoke_session, session_claims
from app.services.auth_redirect import safe_sport_redirect

router = APIRouter(prefix="/directions", include_in_schema=False)
_TTL = 90
_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def _peer(request: Request) -> str:
    host = request.url.netloc
    beauty, sport = settings.BEAUTY_HOST, settings.SPORT_HOST
    if beauty and sport and beauty != sport:
        if host == beauty:
            return sport
        if host == sport:
            return beauty
    return ""


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=302, headers=_HEADERS)


def _to_peer(request: Request, target: str):
    origin = "https://" + _peer(request)
    if request.cookies.get("access_token"):
        return _redirect(origin + "/directions/start?" + urlencode({"next": target}))
    return _redirect(origin + target)


class DirectionRoutes(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method in {"GET", "HEAD"} and _peer(request):
            path = request.url.path
            raw = request.scope["raw_path"].decode("ascii")
            query = request.scope["query_string"].decode("ascii")
            target = raw + ("?" + query if query else "")
            if request.url.netloc == settings.BEAUTY_HOST and (
                path == "/sport" or path.startswith("/sport/")
            ) and path != "/sport/logout":
                return _to_peer(request, target)
            if request.url.netloc == settings.SPORT_HOST and path in {
                "/api/v1/auth/vk/start", "/api/v1/auth/yandex/start",
            }:
                # У провайдеров уже зарегистрирован callback основного стенда.
                params = {"redirect": safe_sport_redirect(request.query_params.get("redirect"))}
                return _redirect("https://" + settings.BEAUTY_HOST + path + "?" + urlencode(params))
        return await call_next(request)


@router.get("/beauty")
async def beauty(request: Request):
    if _peer(request) and request.url.netloc == settings.SPORT_HOST:
        return _to_peer(request, "/")
    return _redirect("/")


def _require_peer(request: Request) -> str:
    peer = _peer(request)
    if not peer:
        raise HTTPException(404)
    return peer


def _key(host: str, step: str, value: str) -> str:
    return f"directions:{host}:{step}:{value}"


def _proof_cookie(state: str) -> str:
    return "__Host-rumi-direction-" + state


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def logout(request: Request, home: str):
    await revoke_session(request.cookies.get("access_token"))
    peer = _peer(request)
    target = f"https://{peer}/directions/signed-out" if peer else home
    response = _redirect(target)
    response.delete_cookie("access_token")
    return response


@router.get("/signed-out")
async def signed_out(request: Request):
    peer = _require_peer(request)
    await revoke_session(request.cookies.get("access_token"))
    home = "/sport/" if peer == settings.SPORT_HOST else "/"
    response = _redirect(f"https://{peer}{home}")
    response.delete_cookie("access_token")
    return response


@router.get("/start")
async def start(request: Request, next: str = "/"):
    peer = _require_peer(request)
    host = request.url.netloc
    target = safe_sport_redirect(next) if host == settings.SPORT_HOST else "/"
    state = secrets.token_urlsafe(24)
    proof = secrets.token_urlsafe(32)
    await get_redis().setex(_key(host, "request", state), _TTL,
                            json.dumps([target, _digest(proof)]))
    response = _redirect(f"https://{peer}/directions/authorize?state={state}")
    response.set_cookie(_proof_cookie(state), proof, max_age=_TTL, secure=True,
                        httponly=True, samesite="lax", path="/")
    return response


@router.get("/authorize")
async def authorize(request: Request, state: str):
    peer = _require_peer(request)
    if not re.fullmatch(r"[A-Za-z0-9_-]{32}", state):
        raise HTTPException(400, "Некорректный переход.")
    redis = get_redis()
    intent = await redis.getdel(_key(peer, "request", state))
    if not intent:
        raise HTTPException(400, "Переход истёк. Откройте направление ещё раз.")
    target, proof = json.loads(intent)
    token = request.cookies.get("access_token", "")
    if not token or not await session_claims(token):
        return _redirect(f"https://{peer}{target}")
    # Код и подтверждение владения браузером идут разными путями. Сам JWT
    # остаётся в Redis этой среды и в host-only cookie двух доверенных хостов.
    code = secrets.token_urlsafe(32)
    await redis.setex(_key(peer, "grant", code), _TTL,
                      json.dumps([state, target, proof, token]))
    return _redirect(f"https://{peer}/directions/finish?code={code}")


@router.get("/finish")
async def finish(request: Request, code: str):
    _require_peer(request)
    grant = await get_redis().getdel(_key(request.url.netloc, "grant", code))
    if not grant:
        raise HTTPException(400, "Переход истёк. Откройте направление ещё раз.")
    state, target, proof, token = json.loads(grant)
    actual = request.cookies.get(_proof_cookie(state), "")
    if not secrets.compare_digest(_digest(actual), proof):
        raise HTTPException(400, "Откройте переход в том же браузере.")
    response = _redirect(target)
    response.delete_cookie(_proof_cookie(state), secure=True, httponly=True)
    claims = await session_claims(token)
    if claims:
        response.set_cookie("access_token", token, max_age=max(0, int(claims["exp"] - time.time())),
                            secure=True, httponly=True, samesite="lax", path="/")
    return response
