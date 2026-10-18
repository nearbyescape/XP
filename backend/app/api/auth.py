"""Admin session: password from ADMIN_PASSWORD, signed JWT in an httpOnly SameSite=Strict cookie.

Mutating admin requests must also carry `X-Requested-With: SignalDesk` (CSRF defence in depth).
Failed logins are rate limited per client IP.
"""

from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque

import jwt
from fastapi import Depends, HTTPException, Request, Response, status

from ..config import Settings, get_settings

COOKIE = "sd_session"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "SignalDesk"
_failures: dict[str, deque] = defaultdict(deque)
MAX_FAILURES, WINDOW_S = 8, 900


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


def check_rate(ip: str) -> None:
    q = _failures[ip]
    now = time.monotonic()
    while q and now - q[0] > WINDOW_S:
        q.popleft()
    if len(q) >= MAX_FAILURES:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many attempts, try again later")


def record_failure(ip: str) -> None:
    _failures[ip].append(time.monotonic())


def verify_password(settings: Settings, username: str, password: str) -> bool:
    if not settings.admin_password:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "admin is disabled (ADMIN_PASSWORD not set)")
    ok_user = hmac.compare_digest(username.encode(), settings.admin_username.encode())
    ok_pass = hmac.compare_digest(password.encode(), settings.admin_password.get_secret_value().encode())
    return ok_user and ok_pass


def issue(response: Response, settings: Settings, username: str) -> None:
    now = int(time.time())
    token = jwt.encode({"sub": username, "iat": now, "exp": now + settings.session_hours * 3600, "scope": "admin"},
                       settings.secret_key.get_secret_value(), algorithm="HS256")
    response.set_cookie(COOKIE, token, max_age=settings.session_hours * 3600, httponly=True,
                        secure=settings.cookie_secure, samesite="strict", path="/api")


def clear(response: Response, settings: Settings) -> None:
    response.delete_cookie(COOKIE, path="/api", secure=settings.cookie_secure, httponly=True, samesite="strict")


def require_admin(request: Request, settings: Settings = Depends(get_settings)) -> str:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not signed in")
    try:
        claims = jwt.decode(token, settings.secret_key.get_secret_value(), algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired") from None
    if claims.get("scope") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing request header")
    return claims["sub"]
