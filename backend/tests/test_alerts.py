import asyncio

import httpx
from sqlalchemy import select

from app import db
from app.config import Settings
from app.engine import runner
from app.engine.clock import Clock
from app.engine.runner import Engine
from app.models import EngineEvent, TelegramOutbox
from app.telegram.client import TelegramClient
from app.telegram.service import TelegramService


class FastClock(Clock):
    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(0.01)


class FlakyMarket:
    name = "binance_spot"
    fine_interval = "1m"

    def __init__(self):
        self.down = True

    async def prices(self, symbols):
        if self.down:
            raise httpx.ConnectError("connection refused")
        return {s: 1.0 for s in symbols}


async def wait_for(kind: str, timeout: float = 5.0) -> None:
    async def poll():
        while True:
            async with db.sessions()() as s:
                if await s.scalar(select(EngineEvent.id).where(EngineEvent.kind == kind)):
                    return
            await asyncio.sleep(0.02)
    await asyncio.wait_for(poll(), timeout)


async def test_market_outage_alerts_admins_once_then_recovery(tmp_path, monkeypatch):
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/alerts.db")
    await db.create_all()
    monkeypatch.setattr(runner, "MARKET_DOWN_ALERT_SECONDS", 0)
    settings = Settings(telegram_bot_token="TOKEN", telegram_admin_chat_ids="42", environment="test",
                        universe="BTCUSDT,ETHUSDT")
    client = TelegramClient("TOKEN", http=httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"ok": True, "result": {"message_id": 1}}))))
    clock = FastClock()
    market = FlakyMarket()
    engine = Engine(settings, market, clock, model=None, telegram=TelegramService(settings, clock, client))

    task = asyncio.create_task(engine.price_loop())
    try:
        await wait_for("market.down")
        await asyncio.sleep(0.1)          # keeps failing: no second alert
        market.down = False
        await wait_for("market.recovered")
    finally:
        task.cancel()

    async with db.sessions()() as s:
        kinds = (await s.scalars(select(EngineEvent.kind).order_by(EngineEvent.id))).all()
        alerts = (await s.scalars(select(TelegramOutbox).where(TelegramOutbox.kind == "alert")
                                  .order_by(TelegramOutbox.id))).all()
        prices = await s.scalar(select(EngineEvent.id).where(EngineEvent.kind == "prices.error"))
    assert kinds.count("market.down") == 1 and kinds.count("market.recovered") == 1
    assert [a.chat_id for a in alerts] == ["42", "42"]
    assert "unreachable" in alerts[0].text and "ConnectError" in alerts[0].text
    assert "reachable again" in alerts[1].text
    assert prices is None


async def test_candle_loop_survives_a_database_outage(tmp_path):
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/outage.db")
    await db.create_all()
    settings = Settings(telegram_bot_token="TOKEN", telegram_admin_chat_ids="42", environment="test",
                        universe="BTCUSDT")
    client = TelegramClient("TOKEN", http=httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"ok": True, "result": {"message_id": 1}}))))
    clock = FastClock()
    engine = Engine(settings, FlakyMarket(), clock, model=None, telegram=TelegramService(settings, clock, client))
    ticks = 0

    async def tick():
        nonlocal ticks
        ticks += 1
        if ticks == 1:
            raise OSError("[Errno -3] Temporary failure in name resolution")
        raise asyncio.CancelledError  # the loop came back for another tick instead of exiting

    engine.candle_tick = tick
    try:
        await engine.candle_loop()
    except asyncio.CancelledError:
        pass
    assert ticks == 2
    async with db.sessions()() as s:
        kinds = (await s.scalars(select(EngineEvent.kind))).all()
        alerts = (await s.scalars(select(TelegramOutbox).where(TelegramOutbox.kind == "alert"))).all()
    assert "candle.error" in kinds and "name resolution" in alerts[0].text


async def test_overlapping_tracker_passes_notify_once(tmp_path):
    """Candle evaluation and the tracker loop can call track_once at the same moment: every target
    hit must still produce exactly one Telegram update."""
    from datetime import datetime, timedelta, timezone

    from app.market.base import Kline
    from app.models import Signal

    db.configure(f"sqlite+aiosqlite:///{tmp_path}/race.db")
    await db.create_all()
    t0 = datetime(2026, 10, 18, 4, tzinfo=timezone.utc)  # 09:30 AM IST

    class Bars(FlakyMarket):
        fine_interval = "15m"

        async def klines_range(self, symbol, interval, start, end):
            await asyncio.sleep(0.01)  # let the other pass interleave
            return [Kline(t0 + timedelta(minutes=15 * i), t0 + timedelta(minutes=15 * (i + 1)),
                          100.3, 101.2 if i == 1 else 100.4, 99.8 if i < 2 else 100.1, 100.3, 1.0) for i in range(3)]

    settings = Settings(telegram_bot_token="TOKEN", telegram_channel_id="@signals", environment="test",
                        universe="BTCUSDT")
    client = TelegramClient("TOKEN", http=httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"ok": True, "result": {"message_id": 1}}))))
    clock = FastClock()
    clock.now = lambda: t0 + timedelta(hours=1)
    engine = Engine(settings, Bars(), clock, model=None, telegram=TelegramService(settings, clock, client))
    async with db.sessions()() as s:
        sig = Signal(uid="RSR-4H:BTCUSDT:x", origin="live", strategy="RSR-4H", symbol="BTCUSDT", side=1,
                     signal_open_at=t0 - timedelta(hours=4), entry_at=t0, expires_at=t0 + timedelta(days=4),
                     entry_price=100.0, take_profit=101.0, stop_loss=94.0, stop_current=94.0, breakeven=True,
                     targets=[[101.0, 0.5], [102.0, 0.3], [103.0, 0.2]], fills=[], targets_hit=0, atr=2.0,
                     tp_atr=0.5, sl_atr=3.0, max_bars=24, regime_coin=1, regime_btc=1, mode="live",
                     published=True, status="ACTIVE", last_price=100.0)
        s.add(sig)
        s.add(TelegramOutbox(chat_id="@signals", kind="signal_new", signal_id=None, text="x", status="sent"))
        await s.flush()
        (await s.scalars(select(TelegramOutbox))).one().signal_id = sig.id
        await s.commit()
    await asyncio.gather(engine.track_once(), engine.track_once())
    async with db.sessions()() as s:
        updates = (await s.scalars(select(TelegramOutbox).where(TelegramOutbox.kind == "signal_update"))).all()
        row = await s.get(Signal, sig.id)
    assert row.targets_hit == 1 and len(updates) == 1
