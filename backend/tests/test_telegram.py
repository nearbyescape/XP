import json
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import select

from app import db
from app.config import Settings
from app.core.session import Session
from app.engine.clock import Clock
from app.models import Signal, TelegramOutbox, TelegramSubscriber
from app.telegram import formatting as fmt
from app.telegram.client import TelegramClient
from app.telegram.service import TelegramService

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)  # 05:30 PM IST, inside the session
STYLE = fmt.Style("SignalDesk", Session(ZoneInfo("Asia/Kolkata"), time(9), time(23)), "Binance USDT futures", 15)


class FixedClock(Clock):
    def __init__(self, t: datetime):
        self.t = t

    def now(self) -> datetime:
        return self.t


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
    text = fmt.new_signal(signal(), STYLE)
    lines = text.split("\n")
    assert lines[0] == "<b>SignalDesk Signal · LONG</b>"
    assert lines[1:6] == ["SOLUSDT · Binance USDT futures · 4H", "Setup: Sweep Reversal · Uptrend (coin + BTC)",
                          "Source close: 18 Oct 2026, 05:30 PM IST", "Entry: 142.30", "Stop loss: 131.80"]
    assert "Take profit: 144.05" in text and "Entry window ends: 18 Oct 2026, 05:45 PM IST" in text
    assert f"Signal: {fmt.public_id(signal())}" in text and len(fmt.public_id(signal())) == 12
    assert "%" not in text  # levels are prices only
    closed = signal(status="CLOSED", exit_reason="TP", exit_price=144.05, exit_at=NOW + timedelta(hours=6, minutes=12),
                    pnl_net=0.0114, r_multiple=0.155)
    assert fmt.close_signal(closed) == "🏆 TP hit · SOLUSDT LONG · signal complete\nResult: +1.14% · held 6h 12m"
    assert fmt.price(0.000123) == "0.00012300" and fmt.price(64000.5) == "64,000.50"
    assert fmt.pair("DOGEUSDT") == "DOGE/USDT"


@pytest.fixture
async def service(tmp_path):
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/tg.db")
    await db.create_all()
    fake = FakeTelegram()
    client = TelegramClient("TOKEN", http=httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    settings = Settings(telegram_bot_token="TOKEN", telegram_channel_id="@signals", telegram_dm_enabled=True,
                        public_base_url="https://signals.example.com", environment="test")
    svc = TelegramService(settings, FixedClock(NOW), client)
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
    assert all("Result: target hit · +1.14%" in e["text"] for e in edits)
    assert all(r["reply_parameters"]["message_id"] > 100 for r in replies)


async def test_bot_commands(service):
    svc, _ = service
    msg = lambda text: {"chat": {"id": 42, "type": "private", "username": "u"}, "text": text}  # noqa: E731
    async with db.sessions()() as s:
        start = await svc.handle_message(s, msg("/start"))
        assert "rule-based" in start and "09:00 AM – 11:00 PM IST" in start
        assert (await s.get(TelegramSubscriber, 42)).active is True
        assert "Unsubscribed" in await svc.handle_message(s, msg("/unsubscribe"))
        assert (await s.get(TelegramSubscriber, 42)).active is False
        assert "No closed signals" in await svc.handle_message(s, msg("/stats"))
        assert "No open signals" in await svc.handle_message(s, msg("/signals"))
        assert "/signals" in await svc.handle_message(s, msg("/whatever"))
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
    text = fmt.new_signal(sig, STYLE)
    assert "TP1 (50%): 144.05\nTP2 (30%): 145.80\nTP3 (20%): 147.55\nAfter TP1: move remaining stop to entry" in text
    assert text.count("%") == 3  # the position sizes only, no price moves

    at = (NOW + timedelta(hours=3)).isoformat()
    tp1 = ladder_signal(fills=[[at, 144.05]], targets_hit=1, stop_current=142.30)
    assert fmt.target_update(tp1, 0) == ("✅ TP1 hit · SOLUSDT LONG · 144.05 · 50% closed\n"
                                         "Move remaining stop to entry: 142.30")
    assert fmt.edited_original(tp1, STYLE).endswith("<b>Status: TP1 ✓ · 50% running, stop at entry</b>")
    two = ladder_signal(fills=[[at, 144.05], [at, 145.80]], targets_hit=2)
    assert fmt.target_update(two, 1) == "✅ TP2 hit · SOLUSDT LONG · 145.80 · 30% closed"
    both = fmt.target_update(two, 0)
    assert both.startswith("✅ TP1 + TP2 hit · SOLUSDT LONG") and "TP2 145.80 · 30% closed" in both

    be = ladder_signal(fills=[[at, 144.05]], targets_hit=1, status="CLOSED", exit_reason="BE", exit_price=142.30,
                       exit_at=NOW + timedelta(hours=9), pnl_net=0.0049, r_multiple=0.047)
    assert fmt.close_signal(be) == "🔒 Stop at entry hit after TP1 · SOLUSDT LONG\nResult: +0.49% · held 9h 00m"
    assert fmt.close_signal(be, 0).startswith("🔒 TP1 hit, then stop at entry · SOLUSDT LONG")
    assert fmt.edited_original(be, STYLE).endswith("<b>Result: TP1, then entry · +0.49%</b>")
    allt = ladder_signal(fills=[[at, 144.05], [at, 145.80], [at, 147.55]], targets_hit=3, status="CLOSED",
                         exit_reason="TP", exit_price=147.55, exit_at=NOW + timedelta(days=1), pnl_net=0.0221,
                         r_multiple=0.21)
    assert fmt.close_signal(allt, 2) == "🏆 TP3 hit · SOLUSDT LONG · signal complete\nResult: +2.21% · held 1d 0h"
    assert fmt.close_signal(allt, 1).startswith("🏆 TP2 + TP3 hit")
    sl = ladder_signal(status="CLOSED", exit_reason="SL", exit_price=131.80, exit_at=NOW + timedelta(hours=30),
                       pnl_net=-0.0745, r_multiple=-1.01)
    assert fmt.close_signal(sl) == "🛑 SL hit · SOLUSDT LONG · 131.80\nResult: -7.45% · held 1d 6h"
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
    assert "Status: TP1 ✓" in edit["text"] and reply["text"].startswith("✅ TP1 hit")
    assert reply["reply_parameters"]["message_id"] == edit["message_id"] > 100
    assert original["chat_id"] == reply["chat_id"] == "@signals"
    assert "disable_notification" not in reply  # inside the session: normal notification


async def test_updates_outside_the_session_are_silent(service, monkeypatch):
    svc, fake = service
    monkeypatch.setattr("app.telegram.service.GROUP_GAP", 0)
    async with db.sessions()() as s:
        sig = ladder_signal(id=None)
        s.add(sig)
        await s.flush()
        await svc.enqueue_signal_new(s, sig)
        await s.commit()
    await drain(svc)
    fake.calls.clear()
    night = datetime(2026, 10, 18, 20, 0, tzinfo=timezone.utc)  # 01:30 AM IST
    svc.clock = FixedClock(night.replace(hour=23))  # processed later still counts as a night-time event
    async with db.sessions()() as s:
        row = await s.get(Signal, sig.id)
        row.status, row.exit_reason, row.exit_price, row.exit_at = "CLOSED", "SL", 131.80, night
        row.pnl_net, row.r_multiple = -0.0745, -1.01
        await svc.enqueue_signal_close(s, row)
        await s.commit()
    await drain(svc)
    reply = next(b for m, b in fake.calls if m == "sendMessage")
    assert reply["text"].startswith("🛑 SL hit") and reply["disable_notification"] is True


async def test_session_greeting_and_summary(service, monkeypatch):
    svc, fake = service
    monkeypatch.setattr("app.telegram.service.GROUP_GAP", 0)
    morning = datetime(2026, 10, 18, 3, 30, tzinfo=timezone.utc)   # 09:00 AM IST
    evening = datetime(2026, 10, 18, 17, 30, tzinfo=timezone.utc)  # 11:00 PM IST
    night = (morning - timedelta(hours=2)).isoformat()                 # 07:00 AM IST: overnight
    async with db.sessions()() as s:
        s.add(ladder_signal(id=101, uid="a", symbol="BTCUSDT", entry_at=morning - timedelta(hours=16),
                            fills=[[night, 144.05]], targets_hit=1))
        s.add(ladder_signal(id=102, uid="b", symbol="ETHUSDT", side=-1, entry_at=morning + timedelta(hours=4),
                            status="CLOSED", exit_reason="SL", exit_price=152.8, pnl_net=-0.0745, r_multiple=-1.0,
                            exit_at=morning + timedelta(hours=9)))
        s.add(ladder_signal(id=103, uid="c", symbol="XRPUSDT", entry_at=morning - timedelta(hours=1),
                            published=False, mode="offhours"))
        s.add(ladder_signal(id=104, uid="d", symbol="SOLUSDT", entry_at=morning + timedelta(hours=8),
                            fills=[[(morning + timedelta(hours=9)).isoformat(), 144.05],
                                   [(morning + timedelta(hours=10)).isoformat(), 145.80],
                                   [(morning + timedelta(hours=11)).isoformat(), 147.55]], targets_hit=3,
                            status="CLOSED", exit_reason="TP", exit_price=147.55, pnl_net=0.0221, r_multiple=0.21,
                            exit_at=morning + timedelta(hours=11)))
        await s.commit()
        hello = await svc.session_start_text(s, morning)
        bye = await svc.session_end_text(s, evening)
    assert hello.startswith("☀️ <b>Good morning, SignalDesk session is open</b>")
    assert "Sun, 18 Oct 2026 · 09:00 AM – 11:00 PM IST" in hello
    assert "Signal checks: 09:30 AM · 01:30 PM · 05:30 PM · 09:30 PM" in hello
    assert "BTCUSDT LONG · TP1 ✓ · 50% running, stop at entry" in hello
    assert "<b>Overnight</b>\nBTCUSDT LONG · TP1 hit · 07:00 AM" in hello
    assert "XRPUSDT" not in hello  # unpublished (outside the session)
    assert bye.startswith("🌙 <b>Session closed · Sun, 18 Oct 2026</b>")
    assert "Signals: 2 · 1 LONG · 1 SHORT" in bye
    assert "Hits: TP1 ×2 · TP2 ×1 · TP3 ×1 · SL ×1" in bye
    assert "<b>Closed (2)</b> · 1 won · 1 lost" in bye and "SOLUSDT LONG · TP3 · +2.21%" in bye
    assert "<b>Open overnight (1)</b>\nBTCUSDT LONG · TP1 ✓" in bye
    assert "Next session: 19 Oct 2026, 09:00 AM IST" in bye
    assert fmt.QUIET not in bye  # signals today
    async with db.sessions()() as s:
        quiet = await svc.session_end_text(s, evening + timedelta(days=1))
    assert "Signals: 0\nHits: TP1 ×0" in quiet and f"\n\n{fmt.QUIET}\n" in quiet

    svc.clock = FixedClock(morning + timedelta(minutes=2))
    await svc._session_message("start", morning)
    await svc._session_message("start", morning)  # restart inside the window: not sent twice
    async with db.sessions()() as s:
        rows = (await s.scalars(select(TelegramOutbox).where(TelegramOutbox.kind == "session_start"))).all()
    assert len(rows) == 1 and rows[0].chat_id == "@signals"


async def test_private_site_has_no_website_links(service):
    svc, _ = service
    private = Settings(telegram_bot_token="TOKEN", telegram_channel_id="@signals", environment="test",
                       public_base_url="https://signals.example.com", site_private=True)
    psvc = TelegramService(private, FixedClock(NOW), svc.client)
    assert svc.site_url == "https://signals.example.com" and psvc.site_url is None
    async with db.sessions()() as s:
        sig = signal(id=None, uid="RSR-4H:SOLUSDT:private")
        s.add(sig)
        await s.flush()
        await psvc.enqueue_signal_new(s, sig)
        await s.commit()
        row = (await s.scalars(select(TelegramOutbox).where(TelegramOutbox.signal_id == sig.id))).one()
    assert row.reply_markup is None
    rules = fmt.rules(psvc.style)
    assert "website" not in rules and "Position size = account × 0.5% ÷ distance from entry to stop" in rules
    assert "10,000 × 0.5% ÷ 7.5% = 667" in rules
    assert "calculator on the website" in fmt.rules(svc.style)
