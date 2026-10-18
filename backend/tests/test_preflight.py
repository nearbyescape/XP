import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy import text

from app import db, preflight
from app.config import Settings
from app.telegram.client import TelegramClient

MODEL = "../research/results/models/mlr_4h_tp0.5_sl3.0_b24"
GOOD = dict(secret_key="x" * 40, admin_password="a long admin password", public_base_url="https://signals.nearby.io",
            app_name="NearbyEscape Signals", telegram_bot_token="TOKEN", telegram_channel_id="@signals",
            telegram_admin_chat_ids="42", universe="BTCUSDT,ETHUSDT", model_path=MODEL, environment="production")


def by_name(checks):
    return {c.name: c for c in checks}


def test_config_checks():
    bad = by_name(preflight.config_checks(Settings(environment="development", market_data_source="replay",
                                                   secret_key="change-me", admin_password=None)))
    assert bad["SECRET_KEY"].status == "FAIL" and bad["ADMIN_PASSWORD"].status == "FAIL"
    assert bad["MARKET_DATA_SOURCE"].status == "FAIL" and bad["ENVIRONMENT"].status == "WARN"
    assert bad["PUBLIC_BASE_URL"].status == "WARN" and bad["APP_NAME"].status == "WARN"
    good = preflight.config_checks(Settings(**GOOD))
    assert {c.status for c in good} == {"PASS"}, [c for c in good if c.status != "PASS"]
    assert "09:30 AM · 01:30 PM · 05:30 PM · 09:30 PM" in by_name(good)["Session"].detail


def test_model_check():
    assert preflight.model_check(Settings(**GOOD)).status == "PASS"
    assert preflight.model_check(Settings(**{**GOOD, "model_path": "/nope"})).status == "FAIL"


def binance(status=200, skew=0.0):
    now = datetime.now(timezone.utc)
    last = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=now.hour % 4)  # current 4H open

    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, text="Service unavailable from a restricted location")
        path = request.url.path
        if path.endswith("/time"):
            return httpx.Response(200, json={"serverTime": int((time.time() + skew) * 1000)})
        if path.endswith("/klines"):
            rows = [[int((last - timedelta(hours=4 * i)).timestamp() * 1000), "1", "2", "0.5", "1.5", "10", 0, "15",
                     5, "4", "6", "0"] for i in (3, 2, 1, 0)]
            return httpx.Response(200, json=rows)
        if path.endswith("/ticker/price"):
            return httpx.Response(200, json=[{"symbol": "BTCUSDT", "price": "64000.5"},
                                             {"symbol": "ETHUSDT", "price": "2400"},
                                             {"symbol": "XYZUSDT", "price": "1"}])
        return httpx.Response(404)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_binance_checks():
    ok = by_name(await preflight.binance_checks(Settings(**GOOD), binance()))
    assert ok["Server clock"].status == "PASS"
    assert ok["Binance futures candles"].status == "PASS" and "2/2 markets" in ok["Binance futures candles"].detail
    assert ok["Binance prices"].detail == "BTCUSDT 64,000.50"
    blocked = await preflight.binance_checks(Settings(**GOOD), binance(status=451))
    assert blocked[0].status == "FAIL" and "refuses this server's location" in blocked[0].detail
    skewed = by_name(await preflight.binance_checks(Settings(**GOOD), binance(skew=30)))
    assert skewed["Server clock"].status == "FAIL" and "NTP" in skewed["Server clock"].detail


def telegram(member: dict, chat_type="channel", admin_ok=True, sent=None):
    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content or b"{}")
        ok = lambda result: httpx.Response(200, json={"ok": True, "result": result})  # noqa: E731
        if method == "getMe":
            return ok({"id": 99, "username": "nearby_signals_bot"})
        if method == "getWebhookInfo":
            return ok({"url": ""})
        if method == "getChat" and body["chat_id"] == "@signals":
            return ok({"id": -100, "title": "Nearby Signals", "type": chat_type})
        if method == "getChat":
            return ok({"id": 42, "type": "private"}) if admin_ok else httpx.Response(
                400, json={"ok": False, "error_code": 400, "description": "Bad Request: chat not found"})
        if method == "getChatMember":
            return ok(member)
        if method == "sendMessage":
            sent.append(body)
            return ok({"message_id": 1})
        return httpx.Response(404, json={"ok": False, "error_code": 404, "description": "Not Found"})
    return TelegramClient("TOKEN", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_telegram_checks():
    admin = {"status": "administrator", "can_post_messages": True, "can_edit_messages": True}
    sent = []
    good = by_name(await preflight.telegram_checks(Settings(**GOOD), telegram(admin, sent=sent), send=True))
    assert good["Telegram bot"].detail == "@nearby_signals_bot"
    assert good["Telegram channel"].status == "PASS" and "can post, edit and pin" in good["Telegram channel"].detail
    assert good["Admin alerts"].status == "PASS" and [m["chat_id"] for m in sent] == ["42"]

    not_admin = by_name(await preflight.telegram_checks(Settings(**GOOD), telegram({"status": "member"})))
    assert not_admin["Telegram channel"].status == "FAIL" and "not an admin" in not_admin["Telegram channel"].detail
    no_edit = by_name(await preflight.telegram_checks(Settings(**GOOD),
                                                      telegram({**admin, "can_edit_messages": False})))
    assert no_edit["Telegram channel"].status == "FAIL"
    group_no_pin = by_name(await preflight.telegram_checks(Settings(**GOOD), telegram(
        {"status": "administrator", "can_pin_messages": False}, chat_type="supergroup")))
    assert group_no_pin["Telegram channel"].status == "WARN"
    no_start = by_name(await preflight.telegram_checks(Settings(**GOOD), telegram(admin, admin_ok=False)))
    assert no_start["Admin alerts"].status == "FAIL" and "press Start" in no_start["Admin alerts"].detail
    unset = await preflight.telegram_checks(Settings(**{**GOOD, "telegram_bot_token": None}))
    assert unset[0].status == "FAIL"


async def test_database_checks(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/pf.db"
    settings = Settings(**{**GOOD, "database_url": url})
    db.configure(url)
    await db.create_all()
    assert (await preflight.database_checks(settings))[0].status == "FAIL"  # never migrated
    head = preflight.migrations_head()
    versions = Path(preflight.__file__).parent.parent.glob("migrations/versions/0*.py")
    assert head == max(v.name[:4] for v in versions)
    async with db.sessions()() as s:
        await s.execute(text("create table alembic_version (version_num varchar(32) not null)"))
        await s.execute(text("insert into alembic_version values ('0003')"))
        await s.commit()
    behind = (await preflight.database_checks(settings))[0]
    assert behind.status == "FAIL" and "migrate" in behind.detail
    async with db.sessions()() as s:
        await s.execute(text("update alembic_version set version_num = :v"), {"v": head})
        await s.commit()
    assert (await preflight.database_checks(settings))[0].status == "PASS"
    cwd = os.getcwd()
    os.chdir(tmp_path)  # works from any directory
    try:
        assert (await preflight.database_checks(settings))[0].status == "PASS"
    finally:
        os.chdir(cwd)


def test_report(capsys):
    code = preflight.report([preflight.Check("PASS", "A", "fine"), preflight.Check("WARN", "Bb", "hmm")])
    assert code == 0 and "READY: 1 passed, 1 warning(s), 0 failure(s)" in capsys.readouterr().out
    assert preflight.report([preflight.Check("FAIL", "C", "broken")]) == 1
