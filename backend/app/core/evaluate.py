"""Turn closed 4h candles into signal candidates for all three strategies.

Selection rules (same as the combined-book backtest):
* a strategy holds at most one open signal per coin and ignores triggers while one is open
* at most one new signal per coin per candle, priority RGP-4H > RSR-4H > MLR-4H
* MLR-4H publishes calls with prob >= threshold only, at most N per candle (most confident
  first); when both directions of a coin qualify it keeps the more confident one

All indicators are causal, so they are computed once over the full history and read at the
evaluated candle. The live engine and the historical replay share `select_candidates`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import indicators as ta
from .catalog import MLR, RGP, RSR
from .ml import MLModel
from .rules import btc_trend_for, regime_pullback, sweep_reversal


@dataclass
class Candidate:
    strategy: str
    symbol: str
    side: int
    signal_open: pd.Timestamp     # open time of the closed signal candle
    close: float
    atr: float
    regime_coin: int
    regime_btc: int
    tp_atr: float
    sl_atr: float
    max_bars: int
    model_prob: float | None = None


@dataclass
class CoinSeries:
    """Per-coin arrays over the full history, aligned with the coin's candle frame."""
    ts: pd.Series
    close: np.ndarray
    atr: np.ndarray
    coin_trend: np.ndarray
    btc_trend: np.ndarray
    sides: dict[str, np.ndarray]


def coin_series(df: pd.DataFrame, btc: pd.DataFrame, symbol: str) -> CoinSeries:
    coin_tr = ta.trend(df["close"])
    btc_tr = btc_trend_for(df, None if symbol == "BTCUSDT" else btc)
    return CoinSeries(
        ts=df["ts"].reset_index(drop=True),
        close=df["close"].to_numpy(float),
        atr=ta.atr(df["high"], df["low"], df["close"], 14).to_numpy(float),
        coin_trend=coin_tr, btc_trend=btc_tr,
        sides={RGP.code: regime_pullback(df, coin_tr, btc_tr),
               RSR.code: sweep_reversal(df, coin_tr, btc_tr)},
    )


def select_candidates(t: pd.Timestamp, rows: dict[str, tuple[CoinSeries, int]],
                      ml_scores: list[tuple[str, int, float]], symbols: list[str],
                      open_positions: set[tuple[str, str]], enabled: set[str],
                      model: MLModel | None) -> list[Candidate]:
    """`rows[symbol] = (series, index of candle t)` for every coin that has candle t."""
    out: list[Candidate] = []
    taken: set[str] = set()

    def make(code, sym, side, spec_tp, spec_sl, bars, prob=None):
        cs, i = rows[sym]
        return Candidate(code, sym, side, t, float(cs.close[i]), float(cs.atr[i]),
                         int(cs.coin_trend[i]), int(cs.btc_trend[i]), spec_tp, spec_sl, bars, prob)

    for sym in symbols:
        if sym not in rows:
            continue
        cs, i = rows[sym]
        if not np.isfinite(cs.atr[i]):
            continue
        for spec in (RGP, RSR):
            if spec.code not in enabled or (spec.code, sym) in open_positions or sym in taken:
                continue
            side = int(cs.sides[spec.code][i])
            if side:
                taken.add(sym)
                out.append(make(spec.code, sym, side, spec.tp_atr, spec.sl_atr, spec.max_bars))

    if MLR.code in enabled and model is not None:
        best: dict[str, tuple[int, float]] = {}
        for sym, side, prob in ml_scores:
            if prob >= model.threshold and prob > best.get(sym, (0, -1.0))[1]:
                best[sym] = (side, prob)
        picked = 0
        for sym, (side, prob) in sorted(best.items(), key=lambda kv: -kv[1][1]):
            if picked >= model.max_per_candle:
                break
            if sym in taken or sym not in rows or sym not in symbols or (MLR.code, sym) in open_positions:
                continue
            taken.add(sym)
            picked += 1
            out.append(make(MLR.code, sym, side, model.tp_atr, model.sl_atr, model.max_bars, prob))
    return out


def evaluate_candle(frames: dict[str, pd.DataFrame], t: pd.Timestamp, symbols: list[str],
                    open_positions: set[tuple[str, str]], enabled: set[str],
                    model: MLModel | None) -> tuple[list[Candidate], list[tuple[str, int, float]]]:
    """Live path: `frames` hold closed candles only; coins whose last candle is `t` are evaluated.
    Returns the candidates and the model's scores (symbol, side, probability)."""
    btc = frames.get("BTCUSDT")
    if btc is None or btc.empty:
        raise ValueError("BTCUSDT candles are required (market regime)")
    rows = {}
    for sym in set(symbols) | ({s for s in model.symbols} if model else set()):
        df = frames.get(sym)
        if df is None or df.empty or df["ts"].iloc[-1] != t:
            continue
        rows[sym] = (coin_series(df, btc, sym), len(df) - 1)
    scores = []
    if MLR.code in enabled and model is not None:
        scores = [(s.symbol, s.side, s.prob) for s in model.score(frames, t)]
    return select_candidates(t, rows, scores, symbols, open_positions, enabled, model), scores


def regime_snapshot(frames: dict[str, pd.DataFrame]) -> dict[str, dict]:
    """Coin and BTC trend plus context numbers on each coin's latest closed candle."""
    btc = frames.get("BTCUSDT")
    out = {}
    for sym, df in frames.items():
        if len(df) < 30:
            continue
        coin = ta.trend(df["close"])
        mkt = btc_trend_for(df, None if sym == "BTCUSDT" else btc)
        c = df["close"]
        out[sym] = {
            "coin": int(coin[-1]), "btc": int(mkt[-1]),
            "close": float(c.iloc[-1]),
            "change_24h": float(c.iloc[-1] / c.iloc[-7] - 1) if len(c) > 7 else None,
            "rsi2": float(ta.rsi(c, 2).iloc[-1]),
            "atr_pct": float((ta.atr(df["high"], df["low"], c, 14) / c).iloc[-1]),
            "candle_open": df["ts"].iloc[-1].isoformat(),
        }
    return out
