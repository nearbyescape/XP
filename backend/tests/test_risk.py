from datetime import timedelta

import httpx
import pandas as pd
import pytest
from sqlalchemy import select

from app import db
from app.config import Settings
from app.core.evaluate import Candidate
from app.core.risk import Exposure, classify, exposure
from app.engine.runner import Engine
from app.engine.watch import review_risk
from app.market.base import Kline
from app.models import Signal, StrategyState, TelegramOutbox
from app.services import repo
from app.telegram import formatting as fmt
from app.telegram.client import TelegramClient
from app.telegram.service import TelegramService

from .test_telegram import NOW, STYLE, FakeTelegram, FixedClock, drain, signal

FILL = [[NOW.isoformat(), 144.05]]


def ladder(**kw):
    base = dict(targets=[[144.05, 0.5], [145.8, 0.3], [147.55, 0.2]], breakeven=True, fills=[], targets_hit=0)
    base.update(kw)
    return signal(**base)


def test_exposure_and_levels():
    rows = [ladder(side=1), ladder(side=1), ladder(side=-1), ladder(side=1, targets_hit=1, fills=FILL),
            ladder(status="CLOSED")]
    e = exposure(rows, 0.5)
    assert (e.open, e.at_risk, e.long, e.short, e.same_direction, e.open_risk_pct) == (4, 3, 2, 1, 2, 1.5)
    # a signal without the stop-to-entry rule keeps risking money after TP1
    assert exposure([ladder(breakeven=False, targets_hit=1, fills=FILL)], 0.5).at_risk == 1

    assert classify(5.9, 6, 8.5, None, 2) is None
    assert classify(6.0, 6, 8.5, None, 2) == "watch"
    assert classify(4.5, 6, 8.5, "watch", 2) == "watch"   # holds until 2 points back inside
    assert classify(3.9, 6, 8.5, "watch", 2) is None
    assert classify(9.0, 6, 8.5, None, 2) == "critical"
    assert classify(66.0, 70, 55, None, 5, higher_is_worse=False) == "watch"
    assert classify(72.0, 70, 55, "watch", 5, higher_is_worse=False) == "watch"
    assert classify(76.0, 70, 55, "watch", 5, higher_is_worse=False) is None
    assert classify(50.0, 70, 55, None, 5, higher_is_worse=False) == "critical"


def test_risk_lines_in_messages():
    text = fmt.new_signal(ladder(risk_at_entry=11), STYLE)
    assert "⚠️ High open risk: 11 signals before TP1, this one included · keep your total under 5%" in text
    assert text.index("High open risk") < text.index("Entry window ends")
    assert "High open risk" not in fmt.new_signal(ladder(risk_at_entry=9), STYLE)
    assert "%" not in fmt.new_signal(ladder(risk_at_entry=9), STYLE).replace("(50%)", "").replace(
        "(30%)", "").replace("(20%)", "")  # the approved format is unchanged below the threshold

    assert (fmt.open_risk(Exposure(5, 4, 3, 1, 0.5), STYLE)
            == "Open risk: 4 signals before TP1 (3 long / 1 short) · 2.0% at 0.5% each")
    assert fmt.open_risk(Exposure(1, 1, 0, 1, 0.5), STYLE).startswith("Open risk: 1 signal before TP1")
    assert fmt.open_risk(Exposure(12, 11, 11, 0, 0.5), STYLE).endswith("⚠️ above the 5% limit")
    assert fmt.open_risk(Exposure(2, 0, 0, 0, 0.5), STYLE).startswith("Open risk: none")

    rules = fmt.rules(STYLE)
    assert rules.startswith("📌 <b>SignalDesk · member rules</b>")
    assert "Risk 0.5% of your account per signal (0.25% while you are new)" in rules
    assert "under 5%" in rules and "that is 10 signals" in rules and "isolated margin" in rules


@pytest.fixture
async def guarded(tmp_path):
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/risk.db")
    await db.create_all()
    fake = FakeTelegram()
    client = TelegramClient("TOKEN", http=httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    settings = Settings(telegram_bot_token="TOKEN", telegram_channel_id="@signals", telegram_admin_chat_ids="42",
                        environment="test")
    return settings, TelegramService(settings, FixedClock(NOW), client), fake


def closed(i, r, strategy="RSR-4H"):
    return ladder(id=None, uid=f"{strategy}:X:{i}", strategy=strategy, status="CLOSED",
                  exit_reason="SL" if r < 0 else "TP", exit_at=NOW + timedelta(hours=i),
                  pnl_net=r * 0.07, r_multiple=r)


async def alerts(s) -> list[str]:
    return [r.text for r in (await s.scalars(select(TelegramOutbox).where(TelegramOutbox.kind == "alert")
                                             .order_by(TelegramOutbox.id))).all()]


async def test_risk_watch_alerts_once_and_when_back_to_normal(guarded):
    settings, svc, _ = guarded
    async with db.sessions()() as s:
        s.add_all([closed(i, -1.0) for i in range(17)])  # 17 stops at 0.5% each: 8.2% below the peak
        await s.flush()
        assert await review_risk(s, settings, svc) == ["drawdown"]
        assert await review_risk(s, settings, svc) == []  # still at the watch level: no repeat
        s.add_all([closed(20 + i, 0.5) for i in range(12)])
        await s.flush()
        assert await review_risk(s, settings, svc) == ["drawdown"]  # back to normal
        texts = await alerts(s)
        assert len(texts) == 2
        assert "risk.drawdown" in texts[0] and "8.2% below their peak" in texts[0] and "17.2%" in texts[0]
        assert "risk.normal" in texts[1] and "Fall from peak back to normal" in texts[1]

        # a strategy's last 30 signals: 20 won
        s.add_all([closed(100 + i, 0.4 if i % 3 else -0.1, "MLR-4H") for i in range(30)])
        await s.flush()
        assert await review_risk(s, settings, svc) == ["win_rate:MLR-4H"]
        assert "MLR-4H won 20 of its last 30 signals (67%)" in (await alerts(s))[-1]

        # 14 longs still before TP1 (plus 3 past TP1 and 2 shorts, which do not count)
        s.add_all([ladder(id=None, uid=f"RGP-4H:L:{i}") for i in range(14)]
                  + [ladder(id=None, uid=f"RGP-4H:T:{i}", targets_hit=1, fills=FILL) for i in range(3)]
                  + [ladder(id=None, uid=f"RGP-4H:S:{i}", side=-1) for i in range(2)])
        await s.flush()
        assert await review_risk(s, settings, svc) == ["concentration"]
        assert "14 published signals are LONG and still before TP1" in (await alerts(s))[-1]
        assert "7.0% at 0.5% each" in (await alerts(s))[-1]
        watch = await repo.get_state(s, "risk_watch")
        assert watch["levels"]["concentration"] == "watch" and watch["measures"]["drawdown"]["level"] is None

        last_eval = {"candle": (NOW - timedelta(hours=4)).isoformat(), "signals": 2}
        status = fmt.status({"clock": NOW.isoformat()}, last_eval, await repo.strategy_states(s), 17, {}, {}, watch,
                            STYLE.session)
        assert "<b>Risk watch</b>" in status and "Same direction before TP1: 14 🟠" in status
        assert "Clock: 18 Oct 2026, 05:30 PM IST" in status
        assert "Last 4H check: 18 Oct 2026, 05:30 PM IST · 2 signal(s)" in status


async def test_pause_all_stops_new_signals_only(guarded):
    settings, svc, _ = guarded
    msg = lambda chat, text: {"chat": {"id": chat, "type": "private", "username": "boss"}, "text": text}  # noqa: E731

    class Market:
        name, fine_interval = "binance_futures", "15m"

        async def klines(self, symbol, interval, start=None, limit=None):
            return [Kline(start, start + timedelta(hours=4), 100.0, 101.0, 99.0, 100.0, 1.0)]

    engine = Engine(settings, Market(), FixedClock(NOW), model=None, telegram=svc)
    live = StrategyState(code="RSR-4H", mode="live", auto_paused=False)
    cand = lambda sym: Candidate("RSR-4H", sym, 1, pd.Timestamp(NOW - timedelta(hours=4)), 100.0, 2.0,  # noqa: E731
                                 1, 1, 0.5, 3.0, 24)

    first = await engine.open_signal(cand("SOLUSDT"), live)  # published normally
    assert first.published and first.risk_at_entry == 1
    async with db.sessions()() as s:
        assert await svc.handle_message(s, msg(7, "/pause")) == fmt.HELP  # members cannot pause
        assert (await repo.publishing(s)) == {}
        assert (await svc.handle_message(s, msg(42, "/pause"))).startswith("⏸️ New signals paused")
        assert "already paused" in await svc.handle_message(s, msg(42, "/pause"))
        assert (await repo.publishing(s))["by"] == "@boss"

    halted = await engine.open_signal(cand("ETHUSDT"), live)
    assert not halted.published and halted.mode == "halted" and halted.risk_at_entry is None
    night = Candidate("RSR-4H", "XRPUSDT", 1, pd.Timestamp(NOW - timedelta(hours=16)), 100.0, 2.0, 1, 1, 0.5, 3.0, 24)
    assert (await engine.open_signal(night, live)).mode == "offhours"  # 05:30 AM IST: never published anyway
    async with db.sessions()() as s:
        # open signals keep their updates while new signals are paused
        row = await s.get(Signal, first.id)
        row.targets_hit, row.fills = 1, [[NOW.isoformat(), 101.0]]
        await svc.enqueue_signal_update(s, row, 0)
        await s.commit()
        kinds = (await s.scalars(select(TelegramOutbox.kind).where(TelegramOutbox.chat_id == "@signals")
                                 .order_by(TelegramOutbox.id))).all()
        assert kinds == ["signal_new", "signal_edit", "signal_update"]  # nothing for the halted signal
        greeting = await svc.session_start_text(s, NOW.replace(hour=3, minute=30) + timedelta(days=1))
        assert fmt.PAUSED in greeting and "Signal checks" not in greeting
        assert "Open risk: none · every open signal is past TP1" in greeting

        assert (await svc.handle_message(s, msg(42, "/resume"))).startswith("▶️ New signals resumed")
        texts = await alerts(s)
        assert len(texts) == 2 and "publishing.paused" in texts[0] and "publishing.resumed" in texts[1]
    again = await engine.open_signal(cand("BNBUSDT"), live)
    assert again.published and again.risk_at_entry == 1  # the halted ETH signal is not counted


async def test_rules_are_posted_and_pinned(guarded, monkeypatch):
    settings, svc, fake = guarded
    monkeypatch.setattr("app.telegram.service.GROUP_GAP", 0)
    async with db.sessions()() as s:
        assert (await svc.handle_message(s, {"chat": {"id": 7, "type": "private"}, "text": "/rules"})
                == fmt.rules(svc.style))
        s.add(TelegramOutbox(chat_id="@signals", kind="rules", text=fmt.rules(svc.style)))
        await s.commit()
    await drain(svc)
    sent = next(b for m, b in fake.calls if m == "sendMessage")
    pin = next(b for m, b in fake.calls if m == "pinChatMessage")
    assert pin == {"chat_id": "@signals", "message_id": 101, "disable_notification": True}
    assert "member rules" in sent["text"]

    # without the pin right the rules stay posted and the administrators are told
    def no_pin(request):
        if request.url.path.endswith("pinChatMessage"):
            return httpx.Response(400, json={"ok": False, "error_code": 400,
                                             "description": "Bad Request: not enough rights to pin a message"})
        return fake.handler(request)

    svc.client = TelegramClient("TOKEN", http=httpx.AsyncClient(transport=httpx.MockTransport(no_pin)))
    async with db.sessions()() as s:
        s.add(TelegramOutbox(chat_id="@signals", kind="rules", text="rules"))
        await s.commit()
    await drain(svc)
    async with db.sessions()() as s:
        row = (await s.scalars(select(TelegramOutbox).where(TelegramOutbox.kind == "rules")
                               .order_by(TelegramOutbox.id.desc()))).first()
        assert row.status == "sent" and row.error.startswith("posted, not pinned")
        assert "Edit messages of others" in (await alerts(s))[-1]
