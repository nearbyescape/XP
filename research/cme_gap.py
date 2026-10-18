"""CME weekend-gap fill study on BTC (and ETH) using Binance spot 1h bars as the price proxy.

CME crypto futures close Friday 16:00 America/Chicago and reopen Sunday 17:00 Chicago.
Gap = spot price at the Sunday reopen vs spot at the Friday close. Trade toward the gap fill at
the reopen: target = Friday close level, stop = `sl_mult` x gap beyond entry, time stop in hours.

    python research/cme_gap.py
"""

from __future__ import annotations

import itertools
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
COST = dict(entry=0.0007, tp=0.0002, exit=0.0008)


def gap_events(d: pd.DataFrame) -> pd.DataFrame:
    d = d.set_index("ts")
    local = d.index.tz_convert("America/Chicago")
    rows = []
    fridays = sorted({t.normalize() for t in local if t.dayofweek == 4})
    for fri in fridays:
        close_t = (fri + pd.Timedelta(hours=16)).tz_convert("UTC")     # Fri 16:00 CT
        open_t = (fri + pd.Timedelta(days=2, hours=17)).tz_convert("UTC")  # Sun 17:00 CT
        last_bar = close_t - pd.Timedelta(hours=1)
        if last_bar not in d.index or open_t not in d.index:
            continue
        rows.append({"fri_close": d.at[last_bar, "close"], "sun_open": d.at[open_t, "open"], "open_t": open_t})
    ev = pd.DataFrame(rows)
    ev["gap"] = ev.sun_open / ev.fri_close - 1
    return ev


def simulate(d: pd.DataFrame, ev: pd.DataFrame, gmin: float, sl_mult: float, hours: int) -> pd.DataFrame:
    d = d.set_index("ts")
    out = []
    for _, e in ev[ev.gap.abs() >= gmin].iterrows():
        side = -1 if e.gap > 0 else 1
        entry = e.sun_open
        tp = e.fri_close
        sl = entry * (1 - side * sl_mult * abs(e.gap))
        w = d.loc[e.open_t: e.open_t + pd.Timedelta(hours=hours - 1)]
        px, why = w.close.iloc[-1], "time"
        for t, b in w.iterrows():
            hit_sl = b.low <= sl if side == 1 else b.high >= sl
            hit_tp = b.high >= tp if side == 1 else b.low <= tp
            if hit_sl:
                px, why = sl, "sl"
                break
            if hit_tp:
                px, why = tp, "tp"
                break
        gross = side * (px / entry - 1)
        out.append({"open_t": e.open_t, "gap": e.gap, "pnl": gross - COST["entry"] - (COST["tp"] if why == "tp" else COST["exit"]), "reason": why})
    return pd.DataFrame(out)


def main():
    rows = []
    for sym in ("BTCUSDT", "ETHUSDT"):
        d = pd.read_parquet(os.path.join(HERE, "data", "parquet", f"{sym}_1h.parquet"))
        ev = gap_events(d)
        print(f"{sym}: {len(ev)} weekends, |gap| median {ev.gap.abs().median():.2%}, p75 {ev.gap.abs().quantile(.75):.2%}")
        for gmin, slm, hrs in itertools.product([0.005, 0.01, 0.02], [1.0, 2.0, 3.0], [24, 72, 120]):
            t = simulate(d, ev, gmin, slm, hrs)
            if t.empty:
                continue
            for per, g in (("2022-24", t[t.open_t < "2025-01-01"]), ("2025-26", t[t.open_t >= "2025-01-01"])):
                if g.empty:
                    continue
                w, l = g.pnl[g.pnl > 0], g.pnl[g.pnl <= 0]
                rows.append({"symbol": sym, "min_gap": gmin, "sl_x_gap": slm, "hours": hrs, "period": per,
                             "trades": len(g), "win_rate": (g.pnl > 0).mean(),
                             "exp_pct": g.pnl.mean() * 100,
                             "pf": w.sum() / -l.sum() if len(l) and l.sum() < 0 else np.inf})
    res = pd.DataFrame(rows)
    res.to_csv(os.path.join(HERE, "results", "cme_gap.csv"), index=False)
    piv = res.pivot_table(index=["symbol", "min_gap", "sl_x_gap", "hours"], columns="period",
                          values=["trades", "win_rate", "pf"])
    pd.set_option("display.width", 200)
    print(piv.round(3).to_string())


if __name__ == "__main__":
    main()
