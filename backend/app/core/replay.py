"""Historical replay of the live selection + lifecycle logic on 4h candles.

Used by `python -m app.cli replay` (seed a staging/demo ledger) and by the parity tests that
compare the engine against research/results/candidates/*_trades.csv.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .catalog import BAR_SECONDS, MLR
from .evaluate import Candidate, coin_series, select_candidates
from .lifecycle import Bar, Costs, TradeState, levels, pnl, step
from .ml import MLModel, universe_features

BAR = pd.Timedelta(seconds=BAR_SECONDS)


@dataclass
class ReplayTrade:
    candidate: Candidate
    state: TradeState
    result: dict = field(default_factory=dict)


def _bar(df_row) -> Bar:
    t = df_row.ts
    return Bar(t, t + BAR, df_row.open, df_row.high, df_row.low, df_row.close)


def ml_scores_by_time(frames: dict[str, pd.DataFrame], model: MLModel,
                      start: pd.Timestamp, end: pd.Timestamp) -> dict[pd.Timestamp, list]:
    feats = universe_features(frames, model.symbols)
    out: dict[pd.Timestamp, list] = {}
    for sym, X in feats.items():
        ts = frames[sym].ts.reset_index(drop=True)
        mask = ((ts >= start) & (ts <= end)).to_numpy()
        if not mask.any():
            continue
        part = X.loc[mask]
        for side in (1, -1):
            probs = model.booster.predict(part.assign(side=side)[model.features])
            for t, p in zip(ts[mask], probs, strict=True):
                out.setdefault(t, []).append((sym, side, float(p)))
    return out


def replay(frames: dict[str, pd.DataFrame], symbols: list[str], enabled: set[str],
           model: MLModel | None, start: pd.Timestamp, end: pd.Timestamp,
           costs: Costs | None = None) -> list[ReplayTrade]:
    costs = costs or Costs()
    btc = frames["BTCUSDT"]
    universe = set(symbols) | (set(model.symbols) if model else set())
    series = {s: coin_series(frames[s], btc, s) for s in universe if s in frames}
    index = {s: pd.Series(np.arange(len(frames[s])), index=frames[s].ts) for s in series}
    scores = ml_scores_by_time(frames, model, start, end) if (model and MLR.code in enabled) else {}

    times = sorted({t for s in series for t in frames[s].ts if start <= t <= end})
    open_trades: dict[tuple[str, str], ReplayTrade] = {}
    done: list[ReplayTrade] = []
    for t in times:
        # 1) the candle opening at t moves every open trade (exits happen at or before its close)
        for key, tr in list(open_trades.items()):
            i = index[key[1]].get(t)
            if i is None:
                continue
            if step(tr.state, _bar(frames[key[1]].iloc[int(i)])):
                tr.result = pnl(tr.state, costs)
                done.append(open_trades.pop(key))
        # 2) evaluate candle t at its close; fills at the next candle's open
        rows = {s: (series[s], int(index[s][t])) for s in series if t in index[s].index}
        cands = select_candidates(t, rows, scores.get(t, []), symbols, set(open_trades), enabled, model)
        for c in cands:
            j = index[c.symbol].get(t + BAR)
            if j is None:
                continue
            entry = float(frames[c.symbol].open.iloc[int(j)])
            tp, sl = levels(c.side, entry, c.atr, c.tp_atr, c.sl_atr)
            st = TradeState(c.side, entry, tp, sl, t + BAR, t + BAR + BAR * c.max_bars)
            open_trades[(c.strategy, c.symbol)] = ReplayTrade(c, st)
    return done + list(open_trades.values())
