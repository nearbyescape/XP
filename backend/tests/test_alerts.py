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
