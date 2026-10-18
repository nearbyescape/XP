"""Market-neutral pair-spread reversion (long A / short beta*B), all 45 pairs of the universe.

Spread  s_t = log A_t - beta_{t-1} * log B_t   (beta = rolling OLS of log prices, lagged)
Signal  z_t = (s_t - mean_W) / std_W  ; |z| > z_in at bar close -> enter both legs next open.
Exits (checked at bar close, executed next open, market orders on both legs):
  TP   : spread has moved tp_k * sigma_entry in our favour
  SL   : spread has moved sl_k * sigma_entry against us
  time : max_bars
Costs: taker + slippage on both legs on entry and exit (0.07% per fill of gross notional).

    python research/pairs.py --tf 4h
"""

from __future__ import annotations

import argparse
import itertools
import os

import numpy as np
import pandas as pd
from numba import njit

from backtest.engine import metrics

HERE = os.path.dirname(os.path.abspath(__file__))
PARQUET = os.path.join(HERE, "data", "parquet")
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
           "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT"]
SPLITS = {"1h": ("2022-03-01", "2025-01-01", "2026-10-18"),
          "4h": ("2019-01-01", "2022-01-01", "2026-10-18")}


@njit(cache=True)
def _pair_sim(oa, ob, ca, cb, z, beta, sd, z_in, tp_k, sl_k, max_bars, cost):
    n = oa.shape[0]
    ent = np.empty(n, np.int64)
    ext = np.empty(n, np.int64)
    pnl = np.empty(n, np.float64)
    side_out = np.empty(n, np.int8)
    k = 0
    i = 0
    while i < n - 2:
        if not (np.isfinite(z[i]) and np.isfinite(beta[i]) and np.isfinite(sd[i])) or abs(z[i]) < z_in:
            i += 1
            continue
        side = -1 if z[i] > 0 else 1          # +1: long A / short B
        e = i + 1
        b = beta[i]
        wa = 1.0 / (1.0 + abs(b))
        wb = b / (1.0 + abs(b))
        pa, pb = oa[e], ob[e]
        sig = sd[i]
        j = e
        exit_j = -1
        while j < n - 1:
            # spread log-change since entry (in spread units)
            ds = (np.log(ca[j] / pa) - b * np.log(cb[j] / pb)) * side
            if ds >= tp_k * sig or ds <= -sl_k * sig or j - e + 1 >= max_bars:
                exit_j = j + 1                   # execute next open
                break
            j += 1
        if exit_j < 0:
            break
        ra = oa[exit_j] / pa - 1.0
        rb = ob[exit_j] / pb - 1.0
        pnl[k] = side * (wa * ra - wb * rb) - 2.0 * cost
        ent[k] = e
        ext[k] = exit_j
        side_out[k] = side
        k += 1
        i = exit_j
    return ent[:k], ext[:k], pnl[:k], side_out[:k]


def load(tf):
    out = {}
    for s in SYMBOLS:
        d = pd.read_parquet(os.path.join(PARQUET, f"{s}_{tf}.parquet")).set_index("ts")
        out[s] = d[["open", "close"]]
    return out


def pair_frame(data, a, b, window):
    d = data[a].join(data[b], lsuffix="_a", rsuffix="_b", how="inner").dropna()
    la, lb = np.log(d.close_a), np.log(d.close_b)
    beta = (la.rolling(window).cov(lb) / lb.rolling(window).var()).shift(1)
    s = la - beta * lb
    mu = s.rolling(window).mean()
    sd = s.rolling(window).std()
    d["z"] = (s - mu) / sd
    d["beta"] = beta
    d["sd"] = sd
    return d


def run(data, tf, window, z_in, tp_k, sl_k, max_bars, cost=0.0007):
    is0, oos0, end = (pd.Timestamp(x, tz="UTC") for x in SPLITS[tf])
    trades = []
    for a, b in itertools.combinations(SYMBOLS, 2):
        d = pair_frame(data, a, b, window)
        e, x, r, sd = _pair_sim(d.open_a.to_numpy(), d.open_b.to_numpy(), d.close_a.to_numpy(),
                                d.close_b.to_numpy(), d.z.to_numpy(), d.beta.to_numpy(),
                                d.sd.to_numpy(), z_in, tp_k, sl_k, max_bars, cost)
        ts = d.index.to_numpy()
        trades.append(pd.DataFrame({"pair": f"{a}/{b}", "entry_time": ts[e], "exit_time": ts[x],
                                    "pnl": r, "side": sd, "bars": x - e}))
    t = pd.concat(trades, ignore_index=True)
    t["entry_time"] = pd.to_datetime(t.entry_time, utc=True)
    t["exit_time"] = pd.to_datetime(t.exit_time, utc=True)
    res = {}
    for name, lo, hi in (("is", is0, oos0), ("oos", oos0, end)):
        m = metrics(t[(t.entry_time >= lo) & (t.entry_time < hi)], (hi - lo).days)
        res.update({f"{name}_{k}": v for k, v in m.items()})
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="4h")
    args = ap.parse_args()
    data = load(args.tf)
    rows = []
    for window, z_in, tp_k, sl_k, mb in itertools.product(
            [120, 360], [2.0, 2.5, 3.0], [0.5, 1.0, 1.5], [2.0, 3.0, 4.0], [12, 30, 60]):
        r = run(data, args.tf, window, z_in, tp_k, sl_k, mb)
        rows.append({"window": window, "z_in": z_in, "tp_k": tp_k, "sl_k": sl_k, "max_bars": mb, **r})
    res = pd.DataFrame(rows)
    res.to_csv(os.path.join(HERE, "results", f"pairs_{args.tf}.csv"), index=False)
    cols = ["window", "z_in", "tp_k", "sl_k", "max_bars", "is_trades", "is_win_rate", "is_profit_factor",
            "is_expectancy_pct", "oos_trades", "oos_signals_per_day", "oos_win_rate", "oos_profit_factor",
            "oos_expectancy_pct"]
    pd.set_option("display.width", 250)
    print(res.sort_values("is_profit_factor", ascending=False)[cols].head(25).round(3).to_string(index=False))
    print("\nmedian OOS expectancy % across grid:", round(res.oos_expectancy_pct.median(), 4))


if __name__ == "__main__":
    main()
