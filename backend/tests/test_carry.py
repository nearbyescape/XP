from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select

from app import db
from app.engine.carry import carry_candidates, carry_over
from app.models import Signal, TelegramOutbox
from app.services import repo
from app.telegram import formatting as fmt

from .test_risk import guarded, ladder  # noqa: F401 - fixture
from .test_telegram import STYLE

LIVE = SimpleNamespace(mode="live", auto_paused=False)
STATES = {"RSR-4H": LIVE, "MLR-4H": LIVE, "RGP-4H": SimpleNamespace(mode="live", auto_paused=True)}
MORNING = datetime(2026, 10, 19, 4, tzinfo=timezone.utc)                 # 09:30 AM IST: the day's first check
AT_0130, AT_0530 = MORNING - timedelta(hours=8), MORNING - timedelta(hours=4)


def night(uid, symbol="SOLUSDT", at=AT_0530, **kw):
    """An unpublished night setup (long, entry 142.30, TP1 144.05, stop 131.80)."""
    base = dict(id=None, uid=uid, symbol=symbol, entry_at=at, signal_open_at=at - timedelta(hours=4),
                expires_at=at + timedelta(days=4), published=False, mode="offhours")
    base.update(kw)
    return ladder(**base)


async def test_morning_carry_over(guarded):  # noqa: F811
    settings, svc, _ = guarded
    session = svc.style.session
    async with db.sessions()() as s:
        s.add_all([
            night("RSR-4H:SOLUSDT:a", at=AT_0130),                      # older night setup on SOL
            night("MLR-4H:SOLUSDT:b", strategy="MLR-4H", model_prob=0.89),  # latest on SOL: carried
            night("RSR-4H:ETHUSDT:c", symbol="ETHUSDT", targets_hit=1,
                  fills=[[AT_0530.isoformat(), 144.05]]),               # reached TP1 overnight
            night("RSR-4H:XRPUSDT:d", symbol="XRPUSDT", status="CLOSED", exit_reason="SL"),
            night("RSR-4H:ADAUSDT:e", symbol="ADAUSDT"),                 # gets a new signal at 09:30
            night("RSR-4H:DOTUSDT:f", symbol="DOTUSDT"),                 # morning price past TP1
            night("RGP-4H:LINKUSDT:g", symbol="LINKUSDT", strategy="RGP-4H"),  # strategy auto-paused
            night("RSR-4H:AVAXUSDT:h", symbol="AVAXUSDT", at=AT_0530 - timedelta(days=1)),  # the night before
            night("RSR-4H:BNBUSDT:i", symbol="BNBUSDT", at=MORNING - timedelta(hours=12),
                  published=True, mode="live"),                         # 09:30 PM yesterday: published
        ])
        await s.commit()
        assert await carry_candidates(s, session, MORNING + timedelta(hours=4), set()) == []  # not the first check
        cands = await carry_candidates(s, session, MORNING, {"ADAUSDT"})
        assert sorted(c.uid for c in cands) == ["MLR-4H:SOLUSDT:b", "RGP-4H:LINKUSDT:g", "RSR-4H:DOTUSDT:f"]
        prices = {"SOLUSDT": 138.0, "DOTUSDT": 145.0, "LINKUSDT": 140.0}

        await repo.set_state(s, "publishing", {"paused": True})
        assert await carry_over(s, settings, MORNING, cands, prices, STATES, svc) == []
        await repo.set_state(s, "publishing", {"paused": False})

        made = await carry_over(s, settings, MORNING, cands, prices, STATES, svc)
        await s.commit()
        assert [m.uid for m in made] == ["MLR-4H:SOLUSDT:b:carry"]
        c = made[0]
        orig = await s.scalar(select(Signal).where(Signal.uid == "MLR-4H:SOLUSDT:b"))
        assert (c.carried_from, c.published, c.mode) == (orig.id, True, "live")
        assert (c.entry_at, c.entry_price) == (MORNING, 138.0)
        assert (c.take_profit, c.stop_loss, c.targets, c.expires_at) == (orig.take_profit, orig.stop_loss, orig.targets,
                                                                        orig.expires_at)
        assert c.signal_open_at == orig.signal_open_at and c.risk_at_entry == 2  # BNB yesterday + this one
        assert not orig.published  # the night signal stays unpublished and tracked

        # a restart during the same check does not post it twice
        assert await carry_over(s, settings, MORNING, cands, prices, STATES, svc) == []
        sent = (await s.scalars(select(TelegramOutbox).where(TelegramOutbox.kind == "signal_new"))).all()
        assert len(sent) == 1
        text = sent[0].text
        assert "🌅 Overnight setup from the 05:30 AM check, still valid" in text
        assert "Source close: 19 Oct 2026, 05:30 AM IST" in text and "Entry: 138.00" in text
        assert "Entry window ends: 19 Oct 2026, 09:45 AM IST" in text
        assert "Overnight" not in fmt.new_signal(orig, STYLE)
