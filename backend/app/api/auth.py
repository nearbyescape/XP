"""Admin session: password from ADMIN_PASSWORD, signed JWT in an httpOnly SameSite=Strict cookie.

Mutating admin requests must also carry `X-Requested-With: SignalDesk` (CSRF defence in depth).
The login form also answers a small arithmetic question (self-hosted captcha, no third party).
Failed logins and wrong answers are rate limited per client IP.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
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
CAPTCHA_TTL_S = 300
_used_captchas: dict[str, float] = {}  # id -> expiry: each question is accepted once


def client_ip(request: Request) -> str:
    """nginx resolves the real client address (trusted proxies only) into X-Real-IP; never trust a
    raw, client-supplied X-Forwarded-For here or the login rate limit can be bypassed."""
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else "?"


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


def _captcha_mac(settings: Settings, cid: str, answer: int) -> str:
    key = settings.secret_key.get_secret_value().encode()
    return hmac.new(key, f"captcha:{cid}:{answer}".encode(), hashlib.sha256).hexdigest()


def new_captcha(settings: Settings) -> dict:
    """A small sum, product or difference. The token carries a keyed hash of the answer (the 80-odd
    possible answers cannot be tried offline without SECRET_KEY), an id and a 5-minute expiry."""
    op = secrets.choice("+−×")
    if op == "+":
        a, b = 2 + secrets.randbelow(18), 2 + secrets.randbelow(8)
        answer = a + b
    elif op == "−":
        b = 2 + secrets.randbelow(8)
        a = b + 1 + secrets.randbelow(12)
        answer = a - b
    else:
        a, b = 2 + secrets.randbelow(8), 2 + secrets.randbelow(5)
        answer = a * b
    cid, now = secrets.token_urlsafe(12), int(time.time())
    token = jwt.encode({"scope": "captcha", "jti": cid, "h": _captcha_mac(settings, cid, answer),
                        "exp": now + CAPTCHA_TTL_S}, settings.secret_key.get_secret_value(), algorithm="HS256")
    return {"question": f"{a} {op} {b}", "token": token, "expires_in": CAPTCHA_TTL_S}


def check_captcha(settings: Settings, token: str, answer: str) -> None:
    """Raise 400 unless `answer` solves the question in `token`, which is unexpired and unused."""
    try:
        claims = jwt.decode(token, settings.secret_key.get_secret_value(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "the security question expired, answer the new one") from None
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid security question") from None
    now = time.time()
    for cid, exp in list(_used_captchas.items()):
        if exp < now:
            del _used_captchas[cid]
    cid = str(claims.get("jti", ""))
    if claims.get("scope") != "captcha" or not cid or cid in _used_captchas:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid security question")
    _used_captchas[cid] = float(claims.get("exp", now + CAPTCHA_TTL_S))
    try:
        value = int(answer.strip().replace("−", "-"))
    except ValueError:
        value = None
    if value is None or not hmac.compare_digest(_captcha_mac(settings, cid, value), str(claims.get("h", ""))):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "wrong answer to the security question")


def issue(response: Response, settings: Settings, username: str) -> None:
    now = int(time.time())
    token = jwt.encode({"sub": username, "iat": now, "exp": now + settings.session_hours * 3600, "scope": "admin"},
                       settings.secret_key.get_secret_value(), algorithm="HS256")
    response.set_cookie(COOKIE, token, max_age=settings.session_hours * 3600, httponly=True,
                        secure=settings.cookie_secure, samesite="strict", path="/api")


def clear(response: Response, settings: Settings) -> None:
    response.delete_cookie(COOKIE, path="/api", secure=settings.cookie_secure, httponly=True, samesite="strict")


def require_site_access(request: Request, settings: Settings = Depends(get_settings)) -> str | None:
    """The dashboard's data and live stream: open when the site is public, the admin session otherwise."""
    if not settings.site_private:
        return None
    return require_admin(request, settings)


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
