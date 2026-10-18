import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app import db
from app.config import Settings
from app.engine.clock import Clock
from app.models import Signal, TelegramOutbox, TelegramSubscriber
from app.telegram import formatting as fmt
from app.telegram.client import TelegramClient
from app.telegram.service import TelegramService

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


class FakeTelegram:
    """Records Bot API calls; message ids increase; chat 999 has blocked the bot."""

    def __init__(self):
        self.calls = []
        self.next_id = 100

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content or b"{}")
        self.calls.append((method, body))
        if body.get("chat_id") in (999, "999"):
            return httpx.Response(403, json={"ok": False, "error_code": 403,
                                             "description": "Forbidden: bot was blocked by the user"})
        if method in ("sendMessage", "editMessageText"):
            self.next_id += 1
            mid = body.get("message_id", self.next_id)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": mid}})
        return httpx.Response(200, json={"ok": True, "result": True})


def signal(**kw):
    base = dict(id=7, uid="RSR-4H:SOLUSDT:x", origin="live", strategy="RSR-4H", symbol="SOLUSDT", side=1,
                signal_open_at=NOW - timedelta(hours=4), entry_at=NOW, expires_at=NOW + timedelta(days=4),
                entry_price=142.30, take_profit=144.05, stop_loss=131.80, atr=3.5, tp_atr=0.5, sl_atr=3.0,
                max_bars=24, regime_coin=1, regime_btc=1, mode="live", published=True, status="ACTIVE",
                mfe=0.0, mae=0.0, last_price=142.3)
    base.update(kw)
    return Signal(**base)


def test_message_templates():
    text = fmt.new_signal(signal(), 0.5)
    assert "LONG · SOL/USDT" in text and "144.05" in text and "131.80" in text
    assert "+1.23%" in text and "−7.38%" in text and "~6.8% notional" in text
    closed = signal(status="CLOSED", exit_reason="TP", exit_price=144.05, exit_at=NOW + timedelta(hours=6, minutes=12),
                    pnl_net=0.0114, r_multiple=0.155)
    assert "Target hit" in fmt.close_signal(closed) and "held 6h 12m" in fmt.close_signal(closed)
    assert fmt.price(0.000123) == "0.00012300" and fmt.price(64000.5) == "64,000.50"
    assert fmt.pair("DOGEUSDT") == "DOGE/USDT"


@pytest.fixture
async def service(tmp_path):
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/tg.db")
    await db.create_all()
    fake = FakeTelegram()
    client = TelegramClient("TOKEN", http=httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    settings = Settings(telegram_bot_token="TOKEN", telegram_channel_id="@signals",
                        public_base_url="https://signals.example.com", environment="test")
    svc = TelegramService(settings, Clock(), client)
    return svc, fake


async def drain(svc):
    async with db.sessions()() as s:
        rows = (await s.scalars(select(TelegramOutbox).where(TelegramOutbox.status == "pending")
                                .order_by(TelegramOutbox.id))).all()
        for r in rows:
            await svc.deliver(s, r)
        await s.commit()


async def test_signal_lifecycle_messages(service, monkeypatch):
    svc, fake = service
    monkeypatch.setattr("app.telegram.service.GROUP_GAP", 0)
    async with db.sessions()() as s:
        s.add(TelegramSubscriber(chat_id=555, username="trader", active=True))
        s.add(TelegramSubscriber(chat_id=999, username="gone", active=True))
        sig = signal(id=None)
        s.add(sig)
        await s.flush()
        await svc.enqueue_signal_new(s, sig)
        await s.commit()
    await drain(svc)
    sends = [b for m, b in fake.calls if m == "sendMessage"]
    assert {b["chat_id"] for b in sends} == {"@signals", "555", "999"}
    assert sends[0]["parse_mode"] == "HTML"
    assert sends[0]["reply_markup"]["inline_keyboard"][0][0]["url"].endswith(f"/signals/{sig.id}")
    async with db.sessions()() as s:
        assert (await s.get(TelegramSubscriber, 999)).active is False  # blocked: unsubscribed

    async with db.sessions()() as s:
        row = await s.get(Signal, sig.id)
        row.status, row.exit_reason, row.exit_price = "CLOSED", "TP", 144.05
        row.exit_at, row.pnl_net, row.r_multiple = NOW + timedelta(hours=6), 0.0114, 0.155
        await svc.enqueue_signal_close(s, row)
        await s.commit()
    fake.calls.clear()
    await drain(svc)
    edits = [b for m, b in fake.calls if m == "editMessageText"]
    replies = [b for m, b in fake.calls if m == "sendMessage"]
    assert {e["chat_id"] for e in edits} == {"@signals", "555"}
    assert all("Target hit" in e["text"] for e in edits)
    assert all(r["reply_parameters"]["message_id"] > 100 for r in replies)


async def test_bot_commands(service):
    svc, _ = service
    msg = lambda text: {"chat": {"id": 42, "type": "private", "username": "u"}, "text": text}  # noqa: E731
    async with db.sessions()() as s:
        assert "rule-based" in await svc.handle_message(s, msg("/start"))
        assert (await s.get(TelegramSubscriber, 42)).active is True
        assert "Unsubscribed" in await svc.handle_message(s, msg("/unsubscribe"))
        assert (await s.get(TelegramSubscriber, 42)).active is False
        assert "No closed signals" in await svc.handle_message(s, msg("/stats"))
        assert "No open signals" in await svc.handle_message(s, msg("/signals"))
        assert "/subscribe" in await svc.handle_message(s, msg("/whatever"))
        group = {"chat": {"id": -100, "type": "supergroup"}, "text": "/start"}
        assert await svc.handle_message(s, group) is None


async def test_admin_alerts_and_status(tmp_path, monkeypatch):
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/tg_admin.db")
    await db.create_all()
    fake = FakeTelegram()
    client = TelegramClient("TOKEN", http=httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    settings = Settings(telegram_bot_token="TOKEN", telegram_channel_id="@signals", environment="test",
                        telegram_admin_chat_ids="42, 43")
    svc = TelegramService(settings, Clock(), client)
    msg = lambda chat_id, text: {"chat": {"id": chat_id, "type": "private"}, "text": text}  # noqa: E731
    async with db.sessions()() as s:
        alert = fmt.alert("SignalDesk", "error", "market.down", "binance_spot unreachable for 5m <timeout>")
        assert alert.startswith("🔴") and "&lt;timeout&gt;" in alert
        assert await svc.enqueue_admin(s, alert, key="market.down")
        assert not await svc.enqueue_admin(s, alert, key="market.down")  # throttled
        assert await svc.enqueue_admin(s, alert, key="market.recovered")
        await s.commit()
        assert "<code>7</code>" in await svc.handle_message(s, msg(7, "/id"))
        assert "Engine status" in await svc.handle_message(s, msg(42, "/status"))
        assert "Engine status" not in await svc.handle_message(s, msg(7, "/status"))  # not an admin
    await drain(svc)
    sends = [b for m, b in fake.calls if m == "sendMessage"]
    assert sorted(b["chat_id"] for b in sends) == ["42", "42", "43", "43"]

    # a delivery that keeps failing for a regular chat raises one admin alert
    monkeypatch.setattr("app.telegram.service.MAX_ATTEMPTS", 1)
    fake.calls.clear()
    fail = lambda request: httpx.Response(400, json={"ok": False, "error_code": 400,  # noqa: E731
                                                     "description": "Bad Request: chat not found"})
    svc.client = TelegramClient("TOKEN", http=httpx.AsyncClient(transport=httpx.MockTransport(fail)))
    async with db.sessions()() as s:
        await svc.enqueue_notice(s, "hello")
        await s.commit()
    await drain(svc)
    async with db.sessions()() as s:
        alerts = (await s.scalars(select(TelegramOutbox).where(TelegramOutbox.kind == "alert",
                                                               TelegramOutbox.status == "pending"))).all()
        assert {a.chat_id for a in alerts} == {"42", "43"} and "chat not found" in alerts[0].text


def ladder_signal(**kw):
    # SOL long: TP1/TP2/TP3 at 0.5/1.0/1.5 ATR (ATR 3.5), stop 3 ATR
    entry, atr = 142.30, 3.5
    targets = [[entry + k * atr, z] for k, z in ((0.5, 0.5), (1.0, 0.3), (1.5, 0.2))]
    base = dict(take_profit=targets[0][0], stop_loss=entry - 3 * atr, targets=targets, breakeven=True,
                stop_current=entry - 3 * atr, fills=[], targets_hit=0)
    base.update(kw)
    return signal(**base)


def test_ladder_message_templates():
    sig = ladder_signal()
    text = fmt.new_signal(sig, 0.5)
    assert "TP1      <code>144.05</code>   +1.23%  · 50%" in text
    assert "TP2      <code>145.80</code>   +2.46%  · 30%" in text and "TP3      <code>147.55</code>" in text
    assert "After TP1, move the stop to entry." in text
    assert "TP1 88% · TP2 44% · TP3 32%" in text

    at = (NOW + timedelta(hours=3)).isoformat()
    tp1 = ladder_signal(fills=[[at, 144.05]], targets_hit=1, stop_current=142.30)
    upd = fmt.target_update(tp1, 0)
    assert "TP1 hit" in upd and "50% closed at <code>144.05</code> (+1.23%)" in upd
    assert "Move the stop to entry <code>142.30</code> · 50% still open" in upd
    assert "🎯 <b>TP1 ✓</b> · 50% still open · stop at entry" in fmt.edited_original(tp1, 0.5)
    two = ladder_signal(fills=[[at, 144.05], [at, 145.80]], targets_hit=2)
    assert "TP1 + TP2 hit" in fmt.target_update(two, 0)
    assert "20% still open · stop at entry" in fmt.target_update(two, 1)

    be = ladder_signal(fills=[[at, 144.05]], targets_hit=1, status="CLOSED", exit_reason="BE", exit_price=142.30,
                       exit_at=NOW + timedelta(hours=9), pnl_net=0.0049, r_multiple=0.047)
    assert "TP1 hit · rest closed at entry" in fmt.close_signal(be) and "net <b>+0.49%</b>" in fmt.close_signal(be)
    allt = ladder_signal(fills=[[at, 144.05], [at, 145.80], [at, 147.55]], targets_hit=3, status="CLOSED",
                         exit_reason="TP", exit_price=147.55, exit_at=NOW + timedelta(days=1), pnl_net=0.0221,
                         r_multiple=0.21)
    assert "All 3 targets hit" in fmt.close_signal(allt) and "Exit" not in fmt.close_signal(allt)
    assert fmt.open_return(tp1, 143.0) == pytest.approx(0.5 * (144.05 / 142.30 - 1) + 0.5 * (143.0 / 142.30 - 1))


async def test_target_update_is_a_reply_and_edits_the_original(service, monkeypatch):
    svc, fake = service
    monkeypatch.setattr("app.telegram.service.GROUP_GAP", 0)
    async with db.sessions()() as s:
        sig = ladder_signal(id=None)
        s.add(sig)
        await s.flush()
        await svc.enqueue_signal_new(s, sig)
        await s.commit()
    await drain(svc)
    original = next(b for m, b in fake.calls if m == "sendMessage")
    fake.calls.clear()
    async with db.sessions()() as s:
        row = await s.get(Signal, sig.id)
        row.fills, row.targets_hit, row.stop_current = [[NOW.isoformat(), 144.05]], 1, 142.30
        await svc.enqueue_signal_update(s, row, 0)
        await s.commit()
    await drain(svc)
    edit = next(b for m, b in fake.calls if m == "editMessageText")
    reply = next(b for m, b in fake.calls if m == "sendMessage")
    assert "TP1 ✓" in edit["text"] and "TP1 hit" in reply["text"]
    assert reply["reply_parameters"]["message_id"] == edit["message_id"] > 100
    assert original["chat_id"] == reply["chat_id"] == "@signals"
