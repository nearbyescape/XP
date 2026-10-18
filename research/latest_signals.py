"""Reference implementation of the two validated strategies on the LATEST closed 4h candle.

Emits signal objects in the schema proposed in docs/crypto-signal-strategy-research.md §8, plus
the current regime of every coin. The live engine must reproduce these outputs bit-for-bit on
the same candles (use this as the parity test).

    python research/latest_signals.py                 # last closed candle in the dataset
    python research/latest_signals.py --at 2026-10-16T20:00Z --risk 0.5
"""

from __future__ import annotations

import argparse
import json
import os

import numpy as np
import pandas as pd

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--at", default="", help="open time of the signal candle (UTC); default = last")
    ap.add_argument("--risk", type=float, default=0.5, help="account risk per signal, percent")
    args = ap.parse_args()

    btc = pd.read_parquet(os.path.join(PARQUET, "BTCUSDT_4h.parquet"))
    signals, regimes = [], {}
    for sym in SYMBOLS:
        df = pd.read_parquet(os.path.join(PARQUET, f"{sym}_4h.parquet"))
        if args.at:
            df = df[df.ts <= pd.Timestamp(args.at)].reset_index(drop=True)
        f = Features(df, btc if sym != "BTCUSDT" else None)
        i = len(df) - 1  # the last CLOSED candle
        regimes[sym] = {"coin": TREND[int(f.trend(200, 24)[i])],
                        "btc": TREND[int(_btc_trend(f, 200, 24)[i])]}
        taken = set()
        for name, (fn, p) in STRATEGIES.items():
            sig = fn(f, p)
            side = int(sig["side"][i])
            if side == 0 or sym in taken:  # one signal per coin per candle (RGP has priority)
                continue
            taken.add(sym)
            close = float(df.close.iloc[i])
            tp = close + side * float(sig["tp_d"][i])
            sl = close - side * float(sig["sl_d"][i])
            sl_pct = abs(sl / close - 1) * 100
            opened = df.ts.iloc[i]
            signals.append({
                "id": f"{name}:{sym}:{opened:%Y-%m-%dT%H:%MZ}",
                "strategy": name, "symbol": sym, "side": "LONG" if side == 1 else "SHORT",
                "signal_candle_close": f"{opened + BAR:%Y-%m-%dT%H:%M:%SZ}",
                "entry_ref": round(close, 6), "take_profit": round(tp, 6), "stop_loss": round(sl, 6),
                "time_stop": f"{opened + BAR * (p['max_bars'] + 1):%Y-%m-%dT%H:%M:%SZ}",
                "tp_pct": round(abs(tp / close - 1) * 100, 2), "sl_pct": round(-sl_pct, 2),
                "rr": round(abs(tp - close) / abs(sl - close), 3),
                "regime": regimes[sym],
                "suggested_risk_pct": args.risk,
                "suggested_notional_pct": round(min(20.0, args.risk / sl_pct * 100), 1),
                "status": "ACTIVE",
            })
    print(json.dumps({"candle_open": str(df.ts.iloc[-1]), "regimes": regimes, "signals": signals},
                     indent=2))


if __name__ == "__main__":
    main()
