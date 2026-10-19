"""Launch checks: python -m app.cli preflight (docs/deployment.md §2).

Run on the server, with the real .env, before the first start and after any change. Every check
prints PASS, WARN or FAIL with what to do; the exit code is 1 when anything fails. Nothing is sent
anywhere unless --send is given (then one test message to each admin chat, never to the channel).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import text

from . import db
from .config import Settings
from .core.catalog import BAR_SECONDS, INTERVAL
from .core.ml import MLModel
from .core.session import Session
from .market.binance import BinanceMarketData
from .telegram.client import TelegramClient, TelegramError

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


@dataclass
class Check:
    status: str
    name: str
    detail: str


def config_checks(settings: Settings) -> list[Check]:
    out = []
    key = settings.secret_key.get_secret_value()
    out.append(Check(FAIL, "SECRET_KEY", "set a random value of 32+ characters (openssl rand -hex 32)")
               if key == "change-me" or len(key) < 32 else Check(PASS, "SECRET_KEY", f"{len(key)} characters"))
    pw = settings.admin_password.get_secret_value() if settings.admin_password else ""
    out.append(Check(FAIL, "ADMIN_PASSWORD", "not set: the admin console is locked") if not pw else
               Check(WARN, "ADMIN_PASSWORD", "shorter than 12 characters") if len(pw) < 12 else
               Check(PASS, "ADMIN_PASSWORD", "set"))
    url = settings.public_base_url
    out.append(Check(WARN, "PUBLIC_BASE_URL", f"{url}: use your https:// domain" + (
        "" if settings.site_private else "; 'Open signal' buttons stay hidden until then"))
               if not url.startswith("https://") or "example." in url else Check(PASS, "PUBLIC_BASE_URL", url))
    out.append(Check(PASS, "Website access", "private: every page and the API need the admin login")
               if settings.site_private else
               Check(WARN, "Website access", "public: anyone with the address sees the signals (SITE_PRIVATE=false)"))
    out.append(Check(PASS, "ENVIRONMENT", "production") if settings.environment == "production" else
               Check(WARN, "ENVIRONMENT", f"{settings.environment} (production expected)"))
    out.append(Check(FAIL, "MARKET_DATA_SOURCE", "replay is for demos; use binance_futures") if settings.is_replay
               else Check(PASS, "MARKET_DATA_SOURCE", settings.market_data_source))
    out.append(Check(PASS, "Search engines", "blocked (noindex)") if not settings.indexing_allowed else
               Check(WARN, "Search engines", "SEARCH_INDEXING=true: the site may be indexed"))
    out.append(Check(WARN, "APP_NAME", "still the default 'SignalDesk': set your brand") if settings.app_name ==
               "SignalDesk" else Check(PASS, "APP_NAME", settings.app_name))
    live = [c for c, m in settings.modes.items() if m == "live"]
    out.append(Check(PASS if live else WARN, "Strategies live", ", ".join(live) or "none: nothing will publish"))
    ses, now = Session.from_settings(settings), datetime.now(timezone.utc)
    checks = " · ".join(ses.label(t, False) for t in ses.checks(ses.local(now).date()))
    out.append(Check(PASS, "Session", f"{settings.session_start}–{settings.session_end} {ses.tzname(now)}, "
                                      f"checks {checks}"))
    return out


def migrations_head() -> str:
    """Latest migration revision, wherever the command is run from (alembic.ini and migrations/ sit
    next to the app package, in the image and in backend/)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


async def database_checks(settings: Settings) -> list[Check]:
    try:
        head, why = migrations_head(), ""
    except Exception as exc:  # noqa: BLE001
        head, why = None, f"{exc.__class__.__name__}: {exc}"
    try:
        db.configure(settings.database_url)
        async with db.sessions()() as s:
            current = await s.scalar(text("select version_num from alembic_version"))
    except Exception as exc:  # noqa: BLE001
        return [Check(FAIL, "Database", f"{exc.__class__.__name__}: {exc}"[:200])]
    if head is None:
        return [Check(WARN, "Database", f"reachable, migration {current}; head unknown ({why})")]
    if current != head:
        return [Check(FAIL, "Database", f"migration {current}, expected {head}: run `docker compose run --rm migrate`")]
    return [Check(PASS, "Database", f"reachable, migrations at {head}")]


def model_check(settings: Settings) -> Check:
    model = MLModel.try_load(settings.model_path)
    if model is None:
        return Check(FAIL, "ML model", f"not found at {settings.model_path}: strategy C (MLR-4H) cannot run")
    return Check(PASS, "ML model", f"{model.version}, {len(model.symbols)} markets, threshold {model.threshold:.3f}")


async def binance_checks(settings: Settings, http: httpx.AsyncClient | None = None) -> list[Check]:
    kind = "spot" if settings.market_data_source == "binance_spot" else "futures"
    urls = settings.binance_spot_urls if kind == "spot" else settings.binance_futures_urls
    base = [u.strip() for u in urls.split(",") if u.strip()]
    http = http or httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
    time_path = {"spot": "/api/v3/time", "futures": "/fapi/v1/time"}[kind]
    try:  # one direct request first, so the reason is clear (the engine's client retries for a minute)
        started = time.time()
        r = await http.get(base[0] + time_path)
    except httpx.HTTPError as exc:
        return [Check(FAIL, "Binance", f"cannot reach {base[0]} ({exc.__class__.__name__}): check the server's "
                                       "internet access / firewall")]
    if r.status_code in (451, 403):
        return [Check(FAIL, "Binance", f"{base[0]} refuses this server's location (HTTP {r.status_code}); host the "
                                       "server in a supported region, e.g. Mumbai, Singapore or the EU")]
    if r.status_code != 200:
        return [Check(FAIL, "Binance", f"{base[0]}{time_path}: HTTP {r.status_code}")]
    skew = (r.json()["serverTime"] / 1000) - (started + time.time()) / 2
    out = [Check(PASS if abs(skew) < 5 else FAIL, "Server clock",
                 f"{skew:+.1f}s vs Binance" + ("" if abs(skew) < 5 else ": enable NTP time sync on the server"))]
    market = BinanceMarketData(base, kind, client=http)
    now = datetime.now(timezone.utc)
    missing, stale, latest = [], [], None
    for sym in settings.symbols:
        try:
            kl = await market.klines(sym, INTERVAL, start=now - timedelta(hours=16), limit=5)
        except Exception:  # noqa: BLE001
            kl = []
        closed = [k for k in kl if k.is_closed(now)]
        if not closed:
            missing.append(sym)
            continue
        latest = closed[-1].close_time
        if now - latest > timedelta(seconds=BAR_SECONDS) + timedelta(minutes=10):
            stale.append(sym)
    if missing:
        out.append(Check(FAIL, f"Binance {kind} candles", f"no 4H candles for {', '.join(missing)}"))
    elif stale:
        out.append(Check(FAIL, f"Binance {kind} candles", f"stale 4H candles for {', '.join(stale)}"))
    else:
        out.append(Check(PASS, f"Binance {kind} candles", f"{len(settings.symbols)}/{len(settings.symbols)} markets, "
                                                          f"last 4H close {latest:%H:%M} UTC"))
    try:
        prices = await market.prices(settings.symbols)
        gap = sorted(set(settings.symbols) - set(prices))
        out.append(Check(FAIL, "Binance prices", f"missing {', '.join(gap)}") if gap else
                   Check(PASS, "Binance prices", f"BTCUSDT {prices.get('BTCUSDT', 0):,.2f}"))
    except Exception as exc:  # noqa: BLE001
        out.append(Check(FAIL, "Binance prices", str(exc)[:200]))
    return out


async def telegram_checks(settings: Settings, client: TelegramClient | None = None, send: bool = False) -> list[Check]:
    if not settings.telegram_enabled:
        return [Check(FAIL, "Telegram bot", "TELEGRAM_BOT_TOKEN is not set (token from @BotFather)")]
    client = client or TelegramClient(settings.telegram_bot_token.get_secret_value(), settings.telegram_api_base)
    try:
        me = await client.get_me()
    except TelegramError as exc:
        return [Check(FAIL, "Telegram bot", f"token rejected or Telegram unreachable: {exc}")]
    out = [Check(PASS, "Telegram bot", f"@{me.get('username')}")]
    try:
        hook = await client.call("getWebhookInfo")
        if hook.get("url"):
            out.append(Check(FAIL, "Telegram webhook", f"a webhook is set ({hook['url']}): the engine reads updates "
                                                       "by polling; remove it with deleteWebhook"))
    except TelegramError:
        pass
    channel = settings.telegram_channel_id
    if not channel:
        out.append(Check(FAIL, "Telegram channel", "TELEGRAM_CHANNEL_ID is not set"))
    else:
        try:
            chat = await client.call("getChat", chat_id=channel)
            member = await client.call("getChatMember", chat_id=channel, user_id=me["id"])
        except TelegramError as exc:
            out.append(Check(FAIL, "Telegram channel", f"{channel}: {exc.description or exc} — add the bot to the "
                                                       "channel as an administrator"))
        else:
            name = f"{chat.get('title', channel)} ({chat.get('type')})"
            if member.get("status") != "administrator":
                out.append(Check(FAIL, "Telegram channel", f"{name}: the bot is {member.get('status')}, not an admin"))
            else:
                group = chat.get("type") in ("group", "supergroup")
                post = group or member.get("can_post_messages")
                edit = group or member.get("can_edit_messages")
                pin = member.get("can_pin_messages") if group else member.get("can_edit_messages")
                if not post or not edit:
                    out.append(Check(FAIL, "Telegram channel", f"{name}: the bot needs 'Post messages' and 'Edit "
                                                               "messages of others'"))
                elif not pin:
                    out.append(Check(WARN, "Telegram channel", f"{name}: the bot cannot pin (member rules)"))
                else:
                    out.append(Check(PASS, "Telegram channel", f"{name}: bot is admin, can post, edit and pin"))
    if not settings.admin_chats:
        out.append(Check(WARN, "Admin alerts", "TELEGRAM_ADMIN_CHAT_IDS is empty: press Start on the bot, send /id, "
                                               "put the number here"))
    for chat_id in settings.admin_chats:
        try:
            await client.call("getChat", chat_id=chat_id)
            if send:
                await client.send_message(chat_id, f"✅ <b>{settings.app_name}</b> preflight: this chat receives "
                                                   "ops alerts.")
            out.append(Check(PASS, "Admin alerts", f"chat {chat_id} reachable" + (", test message sent" if send
                                                                                  else "")))
        except TelegramError as exc:
            out.append(Check(FAIL, "Admin alerts", f"chat {chat_id}: {exc.description or exc} — press Start on the "
                                                   "bot from that account"))
    return out


async def run(settings: Settings, send: bool = False) -> list[Check]:
    checks = config_checks(settings)
    checks += await database_checks(settings)
    checks.append(model_check(settings))
    checks += await binance_checks(settings)
    checks += await telegram_checks(settings, send=send)
    return checks


def report(checks: list[Check]) -> int:
    width = max(len(c.name) for c in checks)
    for c in checks:
        print(f"{c.status}  {c.name:<{width}}  {c.detail}")
    fails, warns = sum(c.status == FAIL for c in checks), sum(c.status == WARN for c in checks)
    print(f"\n{'READY' if not fails else 'NOT READY'}: {len(checks) - fails - warns} passed, {warns} warning(s), "
          f"{fails} failure(s)")
    return 1 if fails else 0
