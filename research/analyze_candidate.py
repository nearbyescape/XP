"""Deep-dive on one strategy/parameter set: per-year / per-coin / per-side tables, exit mix,
signal clustering, concurrent exposure, cost stress and intrabar re-validation on 15m bars.

    python research/analyze_candidate.py --tf 4h --strategy S9_regime_gated_pullback \
        --params "{'rsi_n': 2, 'rsi_lo': 5, 'trend_n': 200, 'sides': 'both', 'tp_atr': 0.5, 'sl_atr': 4.0, 'max_bars': 48}"
"""

from __future__ import annotations

import argparse
import ast
import os

import numpy as np
import pandas as pd

import run_research as R
from backtest.engine import metrics, simulate
from backtest.strategies import STRATEGIES

KEEP = ["trades", "win_rate", "breakeven_wr", "avg_win_pct", "avg_loss_pct", "expectancy_pct",
        "profit_factor", "worst_trade_pct", "max_consec_losses", "acct_return_pct", "acct_max_dd_pct"]


def table(trades: pd.DataFrame, by: str) -> pd.DataFrame:
    rows = {}
    for k, g in trades.groupby(by):
        days = max(1.0, (g.entry_time.max() - g.entry_time.min()).days)
        m = metrics(g, days)
        rows[k] = {c: m[c] for c in KEEP}
    return pd.DataFrame(rows).T


def concurrency(trades: pd.DataFrame) -> pd.Series:
    ev = pd.concat([pd.Series(1, index=trades.entry_time), pd.Series(-1, index=trades.exit_time)])
    return ev.sort_index().cumsum()


def revalidate_on_15m(trades_tf: pd.DataFrame, params: dict, tf: str, cost: dict) -> pd.DataFrame:
    """Re-simulate the SAME signals with 15m bars so TP/SL ordering inside a bar is resolved
    at 15m resolution (15m data exists from 2025-01)."""
    out = []
    bar = pd.Timedelta(tf.replace("m", "min"))
    for sym, g in trades_tf.groupby("symbol"):
        d15 = pd.read_parquet(os.path.join(R.PARQUET, f"{sym}_15m.parquet"))
        g = g[g.entry_time >= d15.ts.iloc[0] + bar]
        if g.empty:
            continue
        side = np.zeros(len(d15), np.int8)
        tp_d = np.full(len(d15), np.nan)
        sl_d = np.full(len(d15), np.nan)
        # the signal bar's close == the 15m bar that ends at entry_time; enter next 15m open
        idx = d15.ts.searchsorted(g.entry_time.to_numpy()) - 1
        ok = idx >= 0
        side[idx[ok]] = g.side.to_numpy()[ok]
        tp_d[idx[ok]] = g.tp_dist.to_numpy()[ok]
        sl_d[idx[ok]] = g.sl_dist.to_numpy()[ok]
        t = simulate(d15, {"side": side, "tp_d": tp_d, "sl_d": sl_d},
                     max_bars=params["max_bars"] * int(bar / pd.Timedelta("15min")), symbol=sym,
                     cost_entry=cost["market_entry"], cost_tp=cost["tp"], cost_exit=cost["exit"])
        out.append(t)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="4h")
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--params", required=True)
    ap.add_argument("--name", default="")
    args = ap.parse_args()
    p = ast.literal_eval(args.params)
    R._init(args.tf, 0.0007, "pro")
    is0, oos0, end = (pd.Timestamp(x, tz="UTC") for x in R.SPLITS[args.tf])
    fn = STRATEGIES[args.strategy]

    frames = []
    for s, f in R._FEATS.items():
        sig = fn(f, p)
        cm = R.COST_MODELS["pro"]
        t = simulate(f.df, sig, max_bars=p["max_bars"], symbol=s, valid=p.get("valid", 1),
                     cost_entry=cm["market_entry"], cost_tp=cm["tp"], cost_exit=cm["exit"])
        # remember the distances used, for the 15m re-validation
        sig_bar = f.df.ts.searchsorted(t.entry_time.to_numpy()) - 1
        t["tp_dist"] = np.asarray(sig["tp_d"])[sig_bar]
        t["sl_dist"] = np.asarray(sig["sl_d"])[sig_bar]
        t["sl_pct"] = t.sl_dist / t.entry * 100
        t["tp_pct"] = t.tp_dist / t.entry * 100
        frames.append(t)
    T = pd.concat(frames, ignore_index=True)
    T = T[(T.entry_time >= is0) & (T.entry_time < end)].copy()
    T["year"] = T.entry_time.dt.year
    T["period"] = np.where(T.entry_time < oos0, "in-sample", "out-of-sample")
    T["side_name"] = T.side.map({1: "long", -1: "short"})

    name = args.name or f"{args.strategy}_{args.tf}"
    outdir = os.path.join(R.RESULTS, "candidates")
    os.makedirs(outdir, exist_ok=True)
    T.to_csv(os.path.join(outdir, f"{name}_trades.csv"), index=False)

    pd.set_option("display.width", 220)
    print(f"== {name}  {p}")
    print("\n-- by period\n", table(T, "period").round(3).to_string())
    print("\n-- by year\n", table(T, "year").round(3).to_string())
    print("\n-- by side (OOS)\n", table(T[T.period == "out-of-sample"], "side_name").round(3).to_string())
    print("\n-- by symbol (OOS)\n", table(T[T.period == "out-of-sample"], "symbol").round(3).to_string())
    print("\n-- exit reasons\n", T.reason.value_counts(normalize=True).round(3).to_string())
    print(f"\n-- typical distances: TP median {T.tp_pct.median():.2f}%  SL median {T.sl_pct.median():.2f}%"
          f"  avg hold {T.bars.mean():.1f} bars")

    daily = T.groupby(T.entry_time.dt.floor("D")).size()
    all_days = pd.date_range(is0.floor("D"), end.floor("D"), freq="D", tz="UTC")
    daily = daily.reindex(all_days, fill_value=0)
    print("\n-- signals per calendar day: mean %.2f | median %d | p90 %d | max %d | days with 0: %.0f%%"
          % (daily.mean(), daily.median(), daily.quantile(0.9), daily.max(), (daily == 0).mean() * 100))
    conc = concurrency(T)
    print("-- concurrent open positions: mean %.2f | p95 %d | max %d" % (conc.mean(), conc.quantile(0.95), conc.max()))

    # cost stress: re-price every trade with worse costs (all taker + 0.1% slippage on stops)
    base_cost = np.where(T.reason == "tp", 0.0007 + 0.0002, 0.0007 + 0.0008)
    for label, cost_tp, cost_stop in (("all-taker 0.07%/side", 0.0014, 0.0014),
                                      ("taker + 0.15% stop slippage", 0.0014, 0.0029),
                                      ("spot 0.1% fees + 0.05% slip", 0.003, 0.003)):
        stressed = T.copy()
        stressed["pnl"] = T.pnl + base_cost - np.where(T.reason == "tp", cost_tp, cost_stop)
        m = metrics(stressed[stressed.period == "out-of-sample"], (end - oos0).days)
        print(f"-- OOS cost stress [{label}]: WR {m['win_rate']:.3f}  PF {m['profit_factor']:.3f}  "
              f"exp {m['expectancy_pct']:.3f}%")

    if args.tf != "15m":
        v = revalidate_on_15m(T, p, args.tf, R.COST_MODELS["pro"])
        if len(v):
            v = v[v.entry_time < end]
            m15 = metrics(v, (end - pd.Timestamp("2025-01-01", tz="UTC")).days)
            same = T[T.entry_time >= v.entry_time.min()]
            mtf = metrics(same, (end - pd.Timestamp("2025-01-01", tz="UTC")).days)
            print(f"\n-- intrabar re-validation on 15m bars (2025-01 .. end): "
                  f"{args.tf}-bars WR {mtf['win_rate']:.3f} PF {mtf['profit_factor']:.3f} exp {mtf['expectancy_pct']:.3f}% (n={mtf['trades']})"
                  f"  vs 15m-bars WR {m15['win_rate']:.3f} PF {m15['profit_factor']:.3f} exp {m15['expectancy_pct']:.3f}% (n={m15['trades']})")


if __name__ == "__main__":
    main()
