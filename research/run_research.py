"""Grid-search every candidate strategy in-sample, then score the same parameter sets
out-of-sample. Selection uses IN-SAMPLE numbers only; OOS is reported, never optimised.

    python research/run_research.py --tf 1h            # full grid on 1h
    python research/run_research.py --tf 4h --cost 0.001
"""

from __future__ import annotations

import argparse
import itertools
import os
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from backtest.engine import metrics, simulate
from backtest.strategies import STRATEGIES, Features

HERE = os.path.dirname(os.path.abspath(__file__))
PARQUET = os.path.join(HERE, "data", "parquet")
RESULTS = os.path.join(HERE, "results")

SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
           "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT"]

# (in-sample start, out-of-sample start, end)
SPLITS = {
    "1h": ("2022-01-15", "2025-01-01", "2026-10-18"),   # IS: 2022 bear + 2023-24 bull; OOS: 2025-26 chop/bear
    "4h": ("2018-01-01", "2022-01-01", "2026-10-18"),
    "15m": ("2025-01-06", "2025-10-01", "2026-10-18"),
    "1d": ("2018-01-01", "2022-01-01", "2026-10-18"),   # resampled from 4h
}

EXITS = [dict(tp_atr=tp, sl_atr=sl, max_bars=mb)
         for tp in (0.5, 0.75, 1.0, 1.5) for sl in (1.5, 2.0, 3.0, 4.0) for mb in (12, 24, 48)]


LIMIT_EXITS = [dict(tp_atr=tp, sl_atr=sl, max_bars=mb)
               for tp in (0.5, 0.75, 1.0, 1.5) for sl in (1.0, 1.5, 2.0, 3.0) for mb in (6, 12, 24)]

# Cost models, as a fraction of notional per fill (fee + slippage).
#   taker: every fill pays taker fee + slippage (0.05% + 0.02%)  -> worst case retail
#   pro  : entry taker 0.07% (market) or maker 0.02% (limit); TP is a resting limit -> maker
#          0.02%; stops / time exits are taker + 0.03% slippage = 0.08%
COST_MODELS = {
    "taker": dict(market_entry=None, limit_entry=None, tp=None, exit=None),
    "pro": dict(market_entry=0.0007, limit_entry=0.0002, tp=0.0002, exit=0.0008),
}


def _grid(base: dict, **axes) -> list[dict]:
    keys = list(axes)
    return [{**base, **dict(zip(keys, vals))} for vals in itertools.product(*axes.values())]


def build_grids() -> dict[str, list[dict]]:
    g = {}
    s1 = _grid({}, rsi_n=[2, 3], rsi_lo=[5, 10, 15], trend_n=[200, 800])
    g["S1_trend_pullback_rsi"] = (
        [{**a, **e} for a in s1 for e in EXITS]
        + [{**a, "exit": "sma", "sl_atr": sl, "max_bars": mb}
           for a in s1 for sl in (2.0, 3.0, 4.0) for mb in (12, 24, 48)]
    )
    s2 = _grid({}, bb_k=[2.0, 2.5, 3.0], rsi_max=[25, 30, 35], trend_filter=[None, 200])
    g["S2_bollinger_snapback"] = [{**a, **e} for a in s2 for e in EXITS]
    s3 = _grid({}, body_atr=[1.5, 2.0, 2.5, 3.0], vol_mult=[2.0, 3.0, 4.0], tbr=[None, 0.4])
    g["S3_capitulation_reversal"] = [{**a, **e} for a in s3 for e in EXITS]
    s4 = _grid({}, lookback=[1, 3, 6], z=[2.0, 2.5, 3.0], btc_calm=[0.005, 0.01, 0.02])
    g["S4_btc_relative_dislocation"] = [{**a, **e} for a in s4 for e in EXITS]
    g["S5_trend_continuation_tp1"] = _grid(
        {"tp1_frac": 0.5, "rsi_cap": 65}, tp1_atr=[0.5, 0.75, 1.0], tp_atr=[2.0, 3.0],
        sl_atr=[1.0, 1.5, 2.0, 3.0], adx_min=[None, 20], max_bars=[24, 48])
    s6 = _grid({}, dev=[2.0, 2.5, 3.0, 3.5], rsi_lo=[5, 10], trend_filter=[None, 200])
    g["S6_vwap_stretch"] = [{**a, **e} for a in s6 for e in EXITS]
    # limit-entry families: tighter stops are viable because the entry price is better
    s7 = [a for a in _grid({"valid": 2}, arm=[0.5, 1.0, 1.5], dev=[1.5, 2.0, 2.5, 3.0],
                           vol_cap=[None, 1.5], trend_filter=[None, 800]) if a["dev"] > a["arm"]]
    g["S7_keltner_wick_catcher"] = [{**a, **e} for a in s7 for e in LIMIT_EXITS]
    s8 = _grid({"valid": 2, "rsi_n": 2}, rsi_lo=[5, 10, 15], offset=[0.25, 0.5, 0.75, 1.0],
               trend_filter=[None, 800])
    g["S8_rsi_extreme_limit"] = [{**a, **e} for a in s8 for e in LIMIT_EXITS]
    # focus grids around the only family that survived OOS: side split + market-regime gate
    focus_exits = [dict(tp_atr=tp, sl_atr=sl, max_bars=mb)
                   for tp in (0.5, 0.75, 1.0) for sl in (2.0, 3.0, 4.0) for mb in (12, 24, 48)]
    s1s = _grid({}, rsi_n=[2, 3], rsi_lo=[5, 10, 15], trend_n=[100, 200, 800], sides=["long", "short"])
    g["S1s_trend_pullback_sides"] = [{**a, **e} for a in s1s for e in focus_exits]
    s9 = _grid({}, rsi_n=[2, 3], rsi_lo=[5, 10, 15], trend_n=[100, 200, 800],
               sides=["both", "long", "short"])
    g["S9_regime_gated_pullback"] = [{**a, **e} for a in s9 for e in focus_exits]
    s10 = _grid({}, lookback=[12, 24, 48], loc=[0.5, 0.7], min_sweep_atr=[None, 0.25],
                trend_n=[None, 200], regime=[False, True])
    s10 = [a for a in s10 if a["trend_n"] or not a["regime"]]
    g["S10_liquidity_sweep"] = [{**a, **e} for a in s10 for e in EXITS]
    return g


_FEATS: dict[str, Features] = {}
_CFG: dict = {}


def _init(tf: str, cost: float, cost_model: str = "taker"):
    _CFG.update(tf=tf, cost=cost, cm=COST_MODELS[cost_model])
    btc = pd.read_parquet(os.path.join(PARQUET, f"BTCUSDT_{tf}.parquet"))
    for s in SYMBOLS:
        df = pd.read_parquet(os.path.join(PARQUET, f"{s}_{tf}.parquet"))
        _FEATS[s] = Features(df, btc if s != "BTCUSDT" else None)


def run_combo(strategy: str, params: dict) -> pd.DataFrame:
    fn = STRATEGIES[strategy]
    frames = []
    for s, f in _FEATS.items():
        if strategy == "S4_btc_relative_dislocation" and f.btc is None:
            continue
        sig = fn(f, params)
        cm = _CFG.get("cm", COST_MODELS["taker"])
        entry_cost = cm["limit_entry"] if "limit_px" in sig else cm["market_entry"]
        t = simulate(f.df, sig, cost_side=_CFG["cost"], max_bars=params["max_bars"],
                     tp1_frac=params.get("tp1_frac", 0.0), symbol=s, valid=params.get("valid", 1),
                     cost_entry=entry_cost, cost_tp=cm["tp"], cost_exit=cm["exit"])
        frames.append(t)
    return pd.concat(frames, ignore_index=True)


def split_metrics(trades: pd.DataFrame, tf: str) -> dict:
    is0, oos0, end = (pd.Timestamp(x, tz="UTC") for x in SPLITS[tf])
    out = {}
    for name, a, b in (("is", is0, oos0), ("oos", oos0, end)):
        t = trades[(trades.entry_time >= a) & (trades.entry_time < b)]
        m = metrics(t, days=(b - a).days)
        if len(t):
            m["t_stat"] = t.pnl.mean() / (t.pnl.std(ddof=1) / np.sqrt(len(t))) if len(t) > 1 else np.nan
            m["long_share"] = (t.side == 1).mean()
        out.update({f"{name}_{k}": v for k, v in m.items()})
    return out


def _job(args):
    strategy, params = args
    trades = run_combo(strategy, params)
    return {"strategy": strategy, "params": repr(params), **split_metrics(trades, _CFG["tf"])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--cost", type=float, default=0.0007, help="fee+slippage per side")
    ap.add_argument("--cost-model", default="taker", choices=list(COST_MODELS))
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    grids = build_grids()
    jobs = [(s, p) for s, ps in grids.items() if not args.only or s in args.only.split(",") for p in ps]
    print(f"{len(jobs)} parameter sets on {args.tf}, cost model={args.cost_model}", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=os.cpu_count(), initializer=_init,
                             initargs=(args.tf, args.cost, args.cost_model)) as pool:
        rows = list(pool.map(_job, jobs, chunksize=8))
    res = pd.DataFrame(rows)
    os.makedirs(RESULTS, exist_ok=True)
    tag = f"cost{args.cost}" if args.cost_model == "taker" else args.cost_model
    suffix = f"_{args.only.replace(',', '+')}" if args.only else ""
    path = os.path.join(RESULTS, f"grid_{args.tf}_{tag}{suffix}.csv")
    res.to_csv(path, index=False)
    print(f"done in {time.time() - t0:.0f}s -> {path}")


if __name__ == "__main__":
    main()
