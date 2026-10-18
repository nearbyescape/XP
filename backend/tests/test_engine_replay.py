"""End-to-end: drive the real Engine (DB, market source, tracker, selection) candle by candle on
a deterministic clock, and compare with the vectorised replay that matches the research."""

from datetime import timedelta

import pandas as pd
from sqlalchemy import select

from app import db
from app.config import Settings
from app.core.catalog import STRATEGIES
from app.core.ml import MLModel
from app.core.replay import replay
from app.engine.clock import Clock
from app.engine.runner import Engine
from app.market.replay import ReplayMarketData
from app.models import Signal

from .conftest import DATA, MODEL, SYMBOLS, needs_data

pytestmark = needs_data


class ManualClock(Clock):
    def __init__(self, t):
        self.t = t

    def now(self):
        return self.t

    async def sleep(self, seconds):
        return None

    @property
    def simulated(self):
        return True


async def test_engine_matches_replay(tmp_path, frames):
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/e2e.db")
    await db.create_all()
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/e2e.db", environment="test")
    start = pd.Timestamp("2026-07-01", tz="UTC")
    end = pd.Timestamp("2026-07-25", tz="UTC")  # ~140 candles: the engine takes ~1.5 s per candle
    clock = ManualClock(start.to_pydatetime() + timedelta(seconds=5))
    model = MLModel(MODEL)
    market = ReplayMarketData(DATA, clock, SYMBOLS)
    engine = Engine(settings, market, clock, model, None)
    await engine.bootstrap()

    t = start
    while t < end:
        clock.t = (t + pd.Timedelta(hours=4)).to_pydatetime() + timedelta(seconds=5)
        await engine.process_candle(t)
        t += pd.Timedelta(hours=4)
    clock.t = end.to_pydatetime() + timedelta(days=10)  # let every trade finish
    await engine.track_once()

    async with db.sessions()() as s:
        rows = (await s.scalars(select(Signal))).all()
    got = pd.DataFrame([{"strategy": r.strategy, "symbol": r.symbol, "side": r.side,
                         "entry_at": pd.Timestamp(r.entry_at), "reason": r.exit_reason,
                         "hits": r.targets_hit} for r in rows])

    full = {s: f for s, f in frames.items()}
    ref_trades = replay(full, SYMBOLS, set(STRATEGIES), model, start, end - pd.Timedelta(hours=4))
    ref = pd.DataFrame([{"strategy": x.candidate.strategy, "symbol": x.candidate.symbol,
                         "side": x.state.side, "entry_at": pd.Timestamp(x.state.entry_at),
                         "reason": x.state.exit_reason, "hits": x.state.targets_hit} for x in ref_trades])

    assert len(got) > 20
    m = ref.merge(got, on=["strategy", "symbol", "side", "entry_at"], how="outer", indicator=True,
                  suffixes=("_ref", "_eng"))
    # identical signal selection; exits may differ only where one 4h candle touched both TP and SL
    # (the engine resolves those with 15m candles, the replay assumes the stop)
    assert (m._merge == "both").mean() >= 0.97, m[m._merge != "both"]
    both = m[m._merge == "both"]
    assert (both.reason_ref == both.reason_eng).mean() >= 0.95
    # TP2/TP3 add more same-candle orderings that 15m candles resolve and 4h candles cannot (e.g. a 4h
    # candle touching both the break-even stop and TP3, which the replay must read as the stop)
    diff = both[both.hits_ref != both.hits_eng]
    assert (both.hits_ref == both.hits_eng).mean() >= 0.9, diff.to_string()
    assert both.hits_eng.max() >= 2  # TP2/TP3 are tracked live
