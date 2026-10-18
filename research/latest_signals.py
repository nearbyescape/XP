"""Reference implementation of the validated strategies on the LATEST closed 4h candle.

RGP-4H and RSR-4H are pure rules. MLR-4H is emitted only if the exported LightGBM model exists
(research/results/models/, produced by `meta_label.py --export`).

Emits signal objects in the schema proposed in docs/crypto-signal-strategy-research.md §8, plus
the current regime of every coin. The live engine must reproduce these outputs bit-for-bit on
the same candles (use this as the parity test). This script is stateless: the live engine must
also suppress a strategy's signal on a coin that still has an open signal from that strategy
(the backtests hold one position per coin per strategy).

    python research/latest_signals.py                 # last closed candle in the dataset
    python research/latest_signals.py --at 2026-10-16T20:00Z --risk 0.5
"""

from __future__ import annotations

import argparse
import json
import os

import numpy as np
import pandas as pd

from backtest import indicators as ta
from backtest.strategies import Features, liquidity_sweep, regime_gated_pullback, _btc_trend

HERE = os.path.dirname(os.path.abspath(__file__))
PARQUET = os.path.join(HERE, "data", "parquet")
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
           "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT"]

# Validated configurations (centre of the out-of-sample plateau). Do not tune these live.
STRATEGIES = {
    "RGP-4H": (regime_gated_pullback,
               {"rsi_n": 2, "rsi_lo": 5, "trend_n": 200, "sides": "both",
                "tp_atr": 0.5, "sl_atr": 4.0, "max_bars": 48}),
    "RSR-4H": (liquidity_sweep,
               {"lookback": 24, "loc": 0.5, "min_sweep_atr": None, "trend_n": 200, "regime": True,
                "tp_atr": 0.5, "sl_atr": 3.0, "max_bars": 24}),
}
BAR = pd.Timedelta("4h")
TREND = {1: "UP", -1: "DOWN", 0: "NEUTRAL"}
MODEL = os.path.join(HERE, "results", "models", "mlr_4h_tp0.5_sl3.0_b24")


def signal_obj(name, sym, side, df, i, tp_d, sl_d, max_bars, regime, risk):
    close = float(df.close.iloc[i])
    tp = close + side * tp_d
    sl = close - side * sl_d
    sl_pct = abs(sl / close - 1) * 100
    opened = df.ts.iloc[i]
    return {
        "id": f"{name}:{sym}:{opened:%Y-%m-%dT%H:%MZ}",
        "strategy": name, "symbol": sym, "side": "LONG" if side == 1 else "SHORT",
        "signal_candle_close": f"{opened + BAR:%Y-%m-%dT%H:%M:%SZ}",
        "entry_ref": round(close, 6), "take_profit": round(tp, 6), "stop_loss": round(sl, 6),
        "time_stop": f"{opened + BAR * (max_bars + 1):%Y-%m-%dT%H:%M:%SZ}",
        "tp_pct": round(abs(tp / close - 1) * 100, 2), "sl_pct": round(-sl_pct, 2),
        "rr": round(tp_d / sl_d, 3),
        "regime": regime,
        "suggested_risk_pct": risk,
        "suggested_notional_pct": round(min(20.0, risk / sl_pct * 100), 1),
        "status": "ACTIVE",
    }


def ml_signals(at, taken, regimes, risk):
    """MLR-4H: score both sides of every coin on the signal candle, keep prob >= threshold,
    best 5 per candle. Features are causal, so computing them on the full history is safe."""
    if not os.path.exists(MODEL + ".txt"):
        return []
    import lightgbm as lgb
    import meta_label

    with open(MODEL + ".json") as fh:
        meta = json.load(fh)
    booster = lgb.Booster(model_file=MODEL + ".txt")
    cands = []
    for sym, (df, X) in meta_label.load("4h").items():
        hit = np.flatnonzero((df.ts == at).to_numpy())
        if not len(hit):
            continue
        i = int(hit[0])
        for side in (1, -1):
            row = X.iloc[[i]].assign(side=side)[meta["features"]]
            prob = float(booster.predict(row)[0])
            if prob >= meta["threshold"]:
                cands.append((prob, sym, side, df, i))
    out = []
    for prob, sym, side, df, i in sorted(cands, key=lambda c: -c[0])[: meta["max_signals_per_candle"]]:
        if sym in taken:
            continue
        taken.add(sym)
        a = float(ta.atr(df.high, df.low, df.close, 14).iloc[i])
        sig = signal_obj("MLR-4H", sym, side, df, i, meta["tp_atr"] * a, meta["sl_atr"] * a,
                         meta["max_bars"], regimes.get(sym), risk)
        sig["model_prob"] = round(prob, 4)
        out.append(sig)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--at", default="", help="open time of the signal candle (UTC); default = last")
    ap.add_argument("--risk", type=float, default=0.5, help="account risk per signal, percent")
    args = ap.parse_args()

    btc = pd.read_parquet(os.path.join(PARQUET, "BTCUSDT_4h.parquet"))
    signals, regimes, taken = [], {}, set()
    for sym in SYMBOLS:
        df = pd.read_parquet(os.path.join(PARQUET, f"{sym}_4h.parquet"))
        if args.at:
            df = df[df.ts <= pd.Timestamp(args.at)].reset_index(drop=True)
        f = Features(df, btc if sym != "BTCUSDT" else None)
        i = len(df) - 1  # the last CLOSED candle
        regimes[sym] = {"coin": TREND[int(f.trend(200, 24)[i])],
                        "btc": TREND[int(_btc_trend(f, 200, 24)[i])]}
        for name, (fn, p) in STRATEGIES.items():
            sig = fn(f, p)
            side = int(sig["side"][i])
            if side == 0 or sym in taken:  # one signal per coin per candle (RGP > RSR > MLR)
                continue
            taken.add(sym)
            signals.append(signal_obj(name, sym, side, df, i, float(sig["tp_d"][i]),
                                      float(sig["sl_d"][i]), p["max_bars"], regimes[sym], args.risk))
    at = df.ts.iloc[-1]
    signals += ml_signals(at, taken, regimes, args.risk)
    print(json.dumps({"candle_open": str(at), "regimes": regimes, "signals": signals}, indent=2))


if __name__ == "__main__":
    main()
