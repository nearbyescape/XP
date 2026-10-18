"""Meta-labelling study: can a gradient-boosted model, trained only on the past, select bars
whose fixed-geometry trade (TP / SL / time-stop in ATR units) wins >= 80% of the time with
positive expectancy AFTER costs?

Walk-forward: expanding training window, retrained every quarter, purged at the boundary.
Out-of-sample predictions start 2025-01-01 (same split as the rule-based grid).

    python research/meta_label.py --tf 1h --tp 0.75 --sl 2.0 --bars 12
"""

from __future__ import annotations

import argparse
import os

import lightgbm as lgb
import numpy as np
import pandas as pd
from numba import njit

from backtest import indicators as ta
from backtest.engine import metrics, simulate

HERE = os.path.dirname(os.path.abspath(__file__))
PARQUET = os.path.join(HERE, "data", "parquet")
RESULTS = os.path.join(HERE, "results")
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
           "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT"]
COST = dict(entry=0.0007, tp=0.0002, exit=0.0008)  # "pro" cost model (see run_research.py)


@njit(cache=True)
def triple_barrier(o, h, l, c, atr, side, tp_m, sl_m, bars, ce, ct, cx):
    """Net PnL of an independent trade signalled at each bar's close (entry next open)."""
    n = o.shape[0]
    out = np.full(n, np.nan)
    for i in range(n - 1):
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue
        e = i + 1
        ep = o[e]
        tp = ep + side * tp_m * a
        sl = ep - side * sl_m * a
        px = np.nan
        tp_hit = False
        last = min(n - 1, e + bars - 1)
        for j in range(e, last + 1):
            if side == 1:
                if j > e and o[j] <= sl:
                    px = o[j]
                elif l[j] <= sl:
                    px = sl
                elif j > e and o[j] >= tp:
                    px = o[j]
                    tp_hit = True
                elif h[j] >= tp:
                    px = tp
                    tp_hit = True
            else:
                if j > e and o[j] >= sl:
                    px = o[j]
                elif h[j] >= sl:
                    px = sl
                elif j > e and o[j] <= tp:
                    px = o[j]
                    tp_hit = True
                elif l[j] <= tp:
                    px = tp
                    tp_hit = True
            if np.isfinite(px):
                break
        if not np.isfinite(px):
            if last < e + bars - 1:
                continue  # not enough future data
            px = c[last]
        gross = side * (px / ep - 1.0)
        out[i] = gross - ce - (ct if tp_hit else cx)
    return out


def features(df: pd.DataFrame, btc: pd.DataFrame) -> pd.DataFrame:
    c, h, l, o, v = df.close, df.high, df.low, df.open, df.volume
    a = ta.atr(h, l, c, 14)
    X = pd.DataFrame(index=df.index)
    X["rsi2"] = ta.rsi(c, 2)
    X["rsi3"] = ta.rsi(c, 3)
    X["rsi14"] = ta.rsi(c, 14)
    for n in (20, 50, 200, 800):
        e = ta.ema(c, n)
        X[f"dist_ema{n}"] = (c - e) / a
        X[f"slope_ema{n}"] = e.pct_change(24)
    X["bbz20"] = ta.zscore(c, 20)
    for n in (1, 3, 6, 12, 24, 72):
        X[f"ret{n}"] = c.pct_change(n)
        X[f"ret{n}_atr"] = c.diff(n) / a
    X["atr_pct"] = a / c
    X["vol_regime"] = a / ta.atr(h, l, c, 200)
    X["vol_ratio"] = v / v.rolling(20).mean().shift(1)
    tbr = df.taker_buy_base / v.replace(0, np.nan)
    X["tbr"] = tbr
    X["tbr3"] = tbr.rolling(3).mean()
    rng = (h - l).replace(0, np.nan)
    X["body_atr"] = (c - o) / a
    X["lower_wick"] = (np.minimum(o, c) - l) / a
    X["upper_wick"] = (h - np.maximum(o, c)) / a
    X["close_loc"] = (c - l) / rng
    X["adx"] = ta.adx(h, l, c, 14)
    X["dist_hi24"] = (h.rolling(24).max() - c) / a
    X["dist_lo24"] = (c - l.rolling(24).min()) / a
    ts = df.ts
    X["hour"] = ts.dt.hour
    X["dow"] = ts.dt.dayofweek
    b = btc.set_index("ts").reindex(ts)
    bc = b.close.reset_index(drop=True).ffill()
    for n in (1, 6, 24):
        X[f"btc_ret{n}"] = bc.pct_change(n).to_numpy()
    X["btc_rsi14"] = ta.rsi(bc, 14).to_numpy()
    X["btc_dist_ema200"] = ((bc - ta.ema(bc, 200)) / bc).to_numpy()
    X["excess_ret24"] = X["ret24"] - X["btc_ret24"]
    return X


def load(tf: str):
    btc = pd.read_parquet(os.path.join(PARQUET, f"BTCUSDT_{tf}.parquet"))
    frames = {}
    for s in SYMBOLS:
        df = pd.read_parquet(os.path.join(PARQUET, f"{s}_{tf}.parquet"))
        X = features(df, btc)
        X["symbol_id"] = SYMBOLS.index(s)
        frames[s] = (df, X)
    # cross-sectional features (rank of 24h return, breadth above EMA200)
    # align on timestamp: coins list at different dates
    r24 = pd.concat({s: frames[s][1]["ret24"].set_axis(frames[s][0].ts) for s in SYMBOLS}, axis=1)
    above = pd.concat({s: (frames[s][1]["dist_ema200"] > 0).astype(float)
                       .where(frames[s][1]["dist_ema200"].notna()).set_axis(frames[s][0].ts)
                       for s in SYMBOLS}, axis=1)
    rank = r24.rank(axis=1, pct=True)
    breadth = above.mean(axis=1)
    for s in SYMBOLS:
        ts = frames[s][0].ts
        frames[s][1]["xs_rank24"] = rank[s].reindex(ts).to_numpy()
        frames[s][1]["breadth200"] = breadth.reindex(ts).to_numpy()
    return frames


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--tp", type=float, default=0.75)
    ap.add_argument("--sl", type=float, default=2.0)
    ap.add_argument("--bars", type=int, default=12)
    ap.add_argument("--oos", default="2025-01-01")
    args = ap.parse_args()

    frames = load(args.tf)
    rows = []
    for s, (df, X) in frames.items():
        o, h, l, c = (df[k].to_numpy(np.float64) for k in ("open", "high", "low", "close"))
        a = ta.atr(df.high, df.low, df.close, 14).to_numpy()
        for side in (1, -1):
            y = triple_barrier(o, h, l, c, a, side, args.tp, args.sl, args.bars,
                               COST["entry"], COST["tp"], COST["exit"])
            d = X.copy()
            d["side"] = side
            d["pnl"] = y
            d["ts"] = df.ts
            d["symbol"] = s
            d["bar"] = np.arange(len(df))
            rows.append(d)
    data = pd.concat(rows, ignore_index=True).dropna(subset=["pnl"])
    data = data[data.ts >= data.ts.min() + pd.Timedelta(days=40)]  # indicator warm-up (EMA800)
    feats = [col for col in data.columns if col not in ("pnl", "ts", "symbol", "bar")]
    data["y"] = (data.pnl > 0).astype(int)

    oos0 = pd.Timestamp(args.oos, tz="UTC")
    end = data.ts.max()
    bar_td = pd.Timedelta(args.tf.replace("m", "min"))
    purge = bar_td * (args.bars + 1)
    quarters = pd.date_range(oos0, end + pd.offsets.QuarterBegin(1), freq="QS", tz="UTC")
    preds = []
    for q0, q1 in zip(quarters[:-1], quarters[1:]):
        tr = data[data.ts < q0 - purge]
        te = data[(data.ts >= q0) & (data.ts < q1)]
        if te.empty:
            continue
        model = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.03, num_leaves=31,
                                   min_child_samples=400, subsample=0.7, subsample_freq=1,
                                   colsample_bytree=0.7, reg_lambda=5.0, verbose=-1)
        model.fit(tr[feats], tr["y"])
        te = te.assign(prob=model.predict_proba(te[feats])[:, 1])
        # IS calibration of the decision threshold: last 12 months of the training window
        cal = tr[tr.ts >= q0 - pd.Timedelta(days=365)]
        cal = cal.assign(prob=model.predict_proba(cal[feats])[:, 1])
        te["q"] = str(q0.date())
        preds.append(te)
        print(f"{q0.date()}: train={len(tr):,} test={len(te):,} base_wr={te.y.mean():.3f}", flush=True)
    P = pd.concat(preds, ignore_index=True)
    base = P.y.mean()
    print(f"\nOOS base win-rate (all bars, geometry TP{args.tp}/SL{args.sl}/{args.bars}b): {base:.3f}")
    print("OOS by predicted-probability bucket (independent, overlapping trades):")
    P["bucket"] = pd.qcut(P.prob, 20, labels=False, duplicates="drop")
    tab = P.groupby("bucket").agg(prob=("prob", "mean"), n=("y", "size"), wr=("y", "mean"),
                                  exp_pct=("pnl", lambda x: x.mean() * 100))
    print(tab.round(4).to_string())

    # Tradable simulation: take signals with prob >= threshold, one position per symbol.
    days = (end - oos0).days
    out = []
    for thr in (0.80, 0.82, 0.84, 0.86, 0.88, 0.90):
        trades = []
        for s, (df, _) in frames.items():
            sub = P[(P.symbol == s) & (P.prob >= thr)]
            side = np.zeros(len(df), np.int8)
            # if both sides qualify on a bar, keep the more confident one
            sub = sub.sort_values("prob").drop_duplicates("bar", keep="last")
            side[sub.bar.to_numpy()] = sub.side.to_numpy()
            a = ta.atr(df.high, df.low, df.close, 14).to_numpy()
            sig = {"side": side, "tp_d": args.tp * a, "sl_d": args.sl * a}
            trades.append(simulate(df, sig, max_bars=args.bars, symbol=s, cost_entry=COST["entry"],
                                   cost_tp=COST["tp"], cost_exit=COST["exit"]))
        t = pd.concat(trades, ignore_index=True)
        t = t[t.entry_time >= oos0]
        m = metrics(t, days)
        m["threshold"] = thr
        out.append(m)
    res = pd.DataFrame(out)
    cols = ["threshold", "trades", "signals_per_day", "win_rate", "breakeven_wr", "expectancy_pct",
            "profit_factor", "acct_return_pct", "acct_max_dd_pct", "max_consec_losses"]
    print("\nOOS tradable (one position per symbol):")
    print(res[cols].round(4).to_string(index=False))
    os.makedirs(RESULTS, exist_ok=True)
    tag = f"{args.tf}_tp{args.tp}_sl{args.sl}_b{args.bars}"
    res.to_csv(os.path.join(RESULTS, f"meta_{tag}.csv"), index=False)
    tab.to_csv(os.path.join(RESULTS, f"meta_buckets_{tag}.csv"))


if __name__ == "__main__":
    main()
