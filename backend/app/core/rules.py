"""Rule-based strategies A (RGP-4H) and B (RSR-4H).

Same logic as research/backtest/strategies.py `regime_gated_pullback` and `liquidity_sweep`
with the validated parameters. Inputs are full-history 4h candle frames with columns
ts, open, high, low, close (ts = candle open time, UTC).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as ta
from .catalog import RGP, RSR


def btc_trend_for(df: pd.DataFrame, btc: pd.DataFrame | None, n: int = 200, slope: int = 24) -> np.ndarray:
    """BTC's trend aligned to `df`'s timestamps (for BTC itself pass btc=None: own trend)."""
    if btc is None:
        return ta.trend(df["close"], n, slope)
    tr = pd.Series(ta.trend(btc["close"], n, slope), index=btc["ts"])
    return tr.reindex(df["ts"]).ffill().fillna(0).to_numpy()


def _side(long_m, short_m) -> np.ndarray:
    lm = np.asarray(long_m, dtype=bool)
    sm = np.asarray(short_m, dtype=bool)
    return np.where(lm, 1, np.where(sm, -1, 0)).astype(np.int8)


def regime_pullback(df: pd.DataFrame, coin_tr: np.ndarray, btc_tr: np.ndarray) -> np.ndarray:
    p = RGP.params
    r = ta.rsi(df["close"], p["rsi_n"])
    long_m = (coin_tr == 1) & (btc_tr == 1) & (r < p["rsi_lo"])
    short_m = (coin_tr == -1) & (btc_tr == -1) & (r > 100 - p["rsi_lo"])
    return _side(long_m, short_m)


def sweep_reversal(df: pd.DataFrame, coin_tr: np.ndarray, btc_tr: np.ndarray) -> np.ndarray:
    p = RSR.params
    n = p["lookback"]
    prior_lo = df["low"].rolling(n).min().shift(1)
    prior_hi = df["high"].rolling(n).max().shift(1)
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    loc = (df["close"] - df["low"]) / rng
    long_m = (df["low"] < prior_lo) & (df["close"] > prior_lo) & (loc > p["loc"])
    short_m = (df["high"] > prior_hi) & (df["close"] < prior_hi) & (loc < 1 - p["loc"])
    long_m &= (coin_tr == 1) & (btc_tr == 1)
    short_m &= (coin_tr == -1) & (btc_tr == -1)
    return _side(long_m, short_m)
