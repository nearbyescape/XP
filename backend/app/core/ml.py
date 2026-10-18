"""Strategy C (MLR-4H): feature construction and LightGBM scoring.

Feature code mirrors research/meta_label.py `features` + `load` exactly (parity-tested): 44
per-coin features, the coin's index in the model universe, cross-sectional 24-candle return rank,
market breadth above EMA200, and the trade direction. The model file and its JSON metadata
(feature order, threshold, universe) are produced by `research/meta_label.py --export`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import indicators as ta

log = logging.getLogger(__name__)


def coin_features(df: pd.DataFrame, btc: pd.DataFrame) -> pd.DataFrame:
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


def universe_features(frames: dict[str, pd.DataFrame], symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Features for every model-universe coin, incl. the cross-sectional ones."""
    btc = frames["BTCUSDT"]
    out: dict[str, pd.DataFrame] = {}
    for i, s in enumerate(symbols):
        if s not in frames or frames[s].empty:
            continue
        X = coin_features(frames[s], btc)
        X["symbol_id"] = i
        out[s] = X
    r24 = pd.concat({s: out[s]["ret24"].set_axis(frames[s].ts) for s in out}, axis=1)
    above = pd.concat({s: (out[s]["dist_ema200"] > 0).astype(float)
                       .where(out[s]["dist_ema200"].notna()).set_axis(frames[s].ts) for s in out}, axis=1)
    rank = r24.rank(axis=1, pct=True)
    breadth = above.mean(axis=1)
    for s in out:
        ts = frames[s].ts
        out[s]["xs_rank24"] = rank[s].reindex(ts).to_numpy()
        out[s]["breadth200"] = breadth.reindex(ts).to_numpy()
    return out


@dataclass
class Score:
    symbol: str
    side: int
    prob: float


class MLModel:
    def __init__(self, path_prefix: str | Path):
        import lightgbm as lgb  # heavy import, only when the model is used

        prefix = str(path_prefix)  # file names contain dots: never use Path.with_suffix here
        self.meta = json.loads(Path(prefix + ".json").read_text())
        self.booster = lgb.Booster(model_file=prefix + ".txt")
        self.features: list[str] = self.meta["features"]
        self.symbols: list[str] = self.meta["symbols"]
        self.threshold: float = float(self.meta["threshold"])
        self.max_per_candle: int = int(self.meta.get("max_signals_per_candle", 5))
        self.version: str = self.meta.get("version") or f"mlr-{self.meta.get('trained_through', '')[:10]}"
        self.tp_atr = float(self.meta["tp_atr"])
        self.sl_atr = float(self.meta["sl_atr"])
        self.max_bars = int(self.meta["max_bars"])

    @classmethod
    def try_load(cls, path_prefix: str | Path) -> MLModel | None:
        try:
            return cls(path_prefix)
        except Exception as exc:  # noqa: BLE001 - engine keeps running A/B without the model
            log.error("MLR model not loaded from %s: %s", path_prefix, exc)
            return None

    def score(self, frames: dict[str, pd.DataFrame], t: pd.Timestamp) -> list[Score]:
        """Both directions of every model-universe coin whose candle `t` exists."""
        feats = universe_features(frames, self.symbols)
        rows, keys = [], []
        for s, X in feats.items():
            hit = np.flatnonzero((frames[s].ts == t).to_numpy())
            if not len(hit):
                continue
            row = X.iloc[[int(hit[0])]]
            for side in (1, -1):
                rows.append(row.assign(side=side)[self.features])
                keys.append((s, side))
        if not rows:
            return []
        probs = self.booster.predict(pd.concat(rows, ignore_index=True))
        return [Score(s, side, float(p)) for (s, side), p in zip(keys, probs, strict=True)]
