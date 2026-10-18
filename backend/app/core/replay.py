"""Historical replay of the live selection + lifecycle logic on 4h candles.

Used by `python -m app.cli replay` (seed a staging/demo ledger) and by the parity tests that
compare the engine against research/results/candidates/*_trades.csv.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .catalog import BAR_SECONDS, MLR, STRATEGIES
from .evaluate import Candidate, coin_series, select_candidates
from .lifecycle import Bar, Costs, TradeState, levels, pnl, step, target_prices
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


def new_trade(c: Candidate, entry: float, entry_at, multi_target: bool = True) -> TradeState:
    """Trade state for a candidate filled at `entry`: the strategy's TP1/TP2/TP3 plan, or (for the
    research parity tests) the single validated target."""
    tp, sl = levels(c.side, entry, c.atr, c.tp_atr, c.sl_atr)
    expires = entry_at + BAR * c.max_bars
    if not multi_target:
        return TradeState(c.side, entry, tp, sl, entry_at, expires)
    spec = STRATEGIES[c.strategy]
    targets = target_prices(c.side, entry, c.atr, spec.targets_atr)
    return TradeState(c.side, entry, targets[0], sl, entry_at, expires, targets=targets,
                      sizes=spec.target_sizes, breakeven=spec.breakeven)


def replay(frames: dict[str, pd.DataFrame], symbols: list[str], enabled: set[str],
           model: MLModel | None, start: pd.Timestamp, end: pd.Timestamp,
           costs: Costs | None = None, multi_target: bool = True) -> list[ReplayTrade]:
    costs = costs or Costs()
    btc = frames["BTCUSDT"]
    universe = set(symbols) | (set(model.symbols) if model else set())
    series = {s: coin_series(frames[s], btc, s) for s in universe if s in frames}
    index = {s: pd.Series(np.arange(len(frames[s])), index=frames[s].ts) for s in series}
    scores = ml_scores_by_time(frames, model, start, end) if (model and MLR.code in enabled) else {}

    times = sorted({t for s in series for t in frames[s].ts if start <= t <= end})
    open_trades: dict[tuple[str, str], ReplayTrade] = {}   # hold their coin until TP1 or exit
    runners: list[ReplayTrade] = []                         # past TP1: stop at entry, coin is free
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
            elif tr.state.targets_hit:
                runners.append(open_trades.pop(key))
        for tr in list(runners):
            i = index[tr.candidate.symbol].get(t)
            if i is not None and step(tr.state, _bar(frames[tr.candidate.symbol].iloc[int(i)])):
                tr.result = pnl(tr.state, costs)
                runners.remove(tr)
                done.append(tr)
        # 2) evaluate candle t at its close; fills at the next candle's open
        rows = {s: (series[s], int(index[s][t])) for s in series if t in index[s].index}
        cands = select_candidates(t, rows, scores.get(t, []), symbols, set(open_trades), enabled, model)
        for c in cands:
            j = index[c.symbol].get(t + BAR)
            if j is None:
                continue
            entry = float(frames[c.symbol].open.iloc[int(j)])
            open_trades[(c.strategy, c.symbol)] = ReplayTrade(c, new_trade(c, entry, t + BAR, multi_target))
    return done + list(open_trades.values()) + runners
