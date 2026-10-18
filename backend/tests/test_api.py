from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import db
from app.config import get_settings
from app.models import Candle, Signal, StrategyState, SystemState

NOW = datetime.now(timezone.utc).replace(microsecond=0)


def make_signal(i, **kw):
    base = dict(uid=f"RGP-4H:BTCUSDT:{i}", origin="live", strategy="RGP-4H", symbol="BTCUSDT", side=1,
                signal_open_at=NOW - timedelta(days=3, hours=4), entry_at=NOW - timedelta(days=3),
                expires_at=NOW + timedelta(days=5), entry_price=100.0, take_profit=101.0, stop_loss=96.0,
                atr=2.0, tp_atr=0.5, sl_atr=2.0, max_bars=48, regime_coin=1, regime_btc=1, mode="live",
                published=True, status="ACTIVE", last_price=100.5, mfe=0.004, mae=-0.002)
    base.update(kw)
    return Signal(**base)


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/api.db")
    monkeypatch.setenv("ADMIN_PASSWORD", "correct horse")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("SEARCH_INDEXING", "false")
    get_settings.cache_clear()
    from app.api import auth
    auth._failures.clear()
    db.configure(get_settings().database_url)
    await db.create_all()
    async with db.sessions()() as s:
        for code in ("RGP-4H", "RSR-4H", "MLR-4H"):
            s.add(StrategyState(code=code, mode="live", auto_paused=False))
        s.add(make_signal(1))
        s.add(make_signal(2, uid="RSR-4H:ETHUSDT:2", strategy="RSR-4H", symbol="ETHUSDT", side=-1,
                          take_profit=99.0, stop_loss=103.0, status="CLOSED", exit_reason="TP", exit_price=99.0,
                          exit_at=NOW - timedelta(days=2), pnl_gross=0.01, pnl_net=0.0091, r_multiple=0.3))
        s.add(make_signal(3, uid="MLR-4H:SOLUSDT:3", strategy="MLR-4H", symbol="SOLUSDT", status="CLOSED",
                          exit_reason="SL", exit_price=96.0, exit_at=NOW - timedelta(days=1), pnl_gross=-0.04,
                          pnl_net=-0.0415, r_multiple=-1.04, model_prob=0.91))
        s.add(make_signal(4, uid="RGP-4H:XRPUSDT:4", symbol="XRPUSDT", published=False, mode="shadow"))
        s.add(SystemState(key="heartbeat", value={"at": NOW.isoformat(), "clock": NOW.isoformat(),
                                                  "simulated": False, "source": "binance_spot"}))
        s.add(SystemState(key="regime", value={"BTCUSDT": {"coin": 1, "btc": 1, "close": 100.0}}))
        for i in range(30):
            t = NOW - timedelta(hours=4 * (30 - i))
            s.add(Candle(symbol="BTCUSDT", interval="4h", open_time=t, open=100, high=101, low=99, close=100.5,
                         volume=1, quote_volume=100, trades=10, taker_buy_base=0.5, taker_buy_quote=50))
        await s.commit()
    from app.main import create_app

    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    get_settings.cache_clear()


async def test_meta_and_noindex(client):
    r = await client.get("/api/meta")
    assert r.status_code == 200
    body = r.json()
    assert [s["code"] for s in body["strategies"]] == ["RGP-4H", "RSR-4H", "MLR-4H"]
    assert body["engine"]["alive"] is True
    assert "noindex" in r.headers["x-robots-tag"]
    robots = await client.get("/robots.txt")
    assert "Disallow: /" in robots.text


async def test_signals_hide_unpublished(client):
    r = (await client.get("/api/signals")).json()
    assert r["total"] == 3
    assert "XRPUSDT" not in {s["symbol"] for s in r["items"]}
    active = (await client.get("/api/signals", params={"status": "active"})).json()
    assert [s["symbol"] for s in active["items"]] == ["BTCUSDT"]
    assert active["items"][0]["progress"] == pytest.approx((100.5 - 96) / 5)
    hidden = await client.get("/api/signals/4")
    assert hidden.status_code == 404
    csv = await client.get("/api/signals.csv", params={"status": "closed"})
    assert csv.text.splitlines()[0].startswith("id,uid,origin,strategy")
    assert len(csv.text.splitlines()) == 3


async def test_stats(client):
    r = (await client.get("/api/stats")).json()
    assert r["kpis"]["signals"] == 2
    assert r["kpis"]["win_rate"] == pytest.approx(50.0)
    assert r["by_strategy"]["MLR-4H"]["signals"] == 1
    eq = (await client.get("/api/stats/equity", params={"risk": 1})).json()
    assert len(eq["points"]) == 2
    assert (await client.get("/api/stats/monthly")).status_code == 200
    candles = (await client.get("/api/candles", params={"symbol": "btcusdt", "limit": 10})).json()
    assert len(candles) == 10 and candles[0]["t"] < candles[-1]["t"]


async def test_admin_flow(client):
    assert (await client.get("/api/admin/overview")).status_code == 401
    bad = await client.post("/api/admin/login", json={"username": "admin", "password": "nope"})
    assert bad.status_code == 401
    ok = await client.post("/api/admin/login", json={"username": "admin", "password": "correct horse"})
    assert ok.status_code == 204 and "sd_session" in ok.headers["set-cookie"]
    assert "httponly" in ok.headers["set-cookie"].lower()
    ov = (await client.get("/api/admin/overview")).json()
    assert {s["code"] for s in ov["strategies"]} == {"RGP-4H", "RSR-4H", "MLR-4H"}
    no_csrf = await client.put("/api/admin/strategies/MLR-4H", json={"mode": "shadow"})
    assert no_csrf.status_code == 403
    upd = await client.put("/api/admin/strategies/MLR-4H", json={"mode": "shadow"},
                           headers={"X-Requested-With": "SignalDesk"})
    assert upd.json()["mode"] == "shadow"
    tg = await client.post("/api/admin/telegram/test", json={}, headers={"X-Requested-With": "SignalDesk"})
    assert tg.status_code == 409  # no bot token configured
    shadow = (await client.get("/api/admin/signals", params={"published": "false"})).json()
    assert [s["symbol"] for s in shadow] == ["XRPUSDT"]


async def test_login_rate_limit(client):
    # rotating a spoofed X-Forwarded-For must not reset the limit
    for i in range(8):
        await client.post("/api/admin/login", json={"username": "x", "password": "y"},
                          headers={"X-Forwarded-For": f"10.0.0.{i}"})
    r = await client.post("/api/admin/login", json={"username": "admin", "password": "correct horse"})
    assert r.status_code == 429
