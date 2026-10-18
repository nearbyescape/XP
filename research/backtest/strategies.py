"""Candidate signal strategies.

Every builder takes (features, params) and returns the dict consumed by engine.simulate:
    side  : int8 array, +1 = long signal, -1 = short signal, 0 = nothing (decided at bar close)
    tp_d  : take-profit distance in price units (array)
    sl_d  : stop-loss distance in price units (array)
    tp1_d : optional first target distance (scale-out)
    dyn_long / dyn_short : optional bool arrays, "exit at this bar's close"
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from . import indicators as ta


class Features:
    """Lazily computed, memoised indicator cache for one symbol/timeframe."""

    def __init__(self, df: pd.DataFrame, btc: pd.DataFrame | None = None):
        self.df = df
        self.btc = btc
        self.c = df["close"]
        self.n = len(df)

    @lru_cache(maxsize=None)
    def ema(self, n):
        return ta.ema(self.c, n)

    @lru_cache(maxsize=None)
    def sma(self, n):
        return ta.sma(self.c, n)

    @lru_cache(maxsize=None)
    def rsi(self, n):
        return ta.rsi(self.c, n)

    @lru_cache(maxsize=None)
    def atr(self, n=14):
        return ta.atr(self.df["high"], self.df["low"], self.c, n)

    @lru_cache(maxsize=None)
    def bb(self, n, k):
        return ta.bollinger(self.c, n, k)

    @lru_cache(maxsize=None)
    def vwap(self, n):
        return ta.rolling_vwap(self.df, n)

    @lru_cache(maxsize=None)
    def vol_ratio(self, n=20):
        v = self.df["volume"]
        return v / v.rolling(n, min_periods=n).mean().shift(1)

    @lru_cache(maxsize=None)
    def taker_buy_ratio(self):
        return self.df["taker_buy_base"] / self.df["volume"].replace(0, np.nan)

    @lru_cache(maxsize=None)
    def adx(self, n=14):
        return ta.adx(self.df["high"], self.df["low"], self.c, n)

    @lru_cache(maxsize=None)
    def trend(self, n, slope_bars):
        """+1 up-trend, -1 down-trend, 0 otherwise: price vs EMA(n) and EMA(n) slope."""
        e = self.ema(n)
        up = (self.c > e) & (e > e.shift(slope_bars))
        dn = (self.c < e) & (e < e.shift(slope_bars))
        return np.where(up, 1, np.where(dn, -1, 0))

    @lru_cache(maxsize=None)
    def btc_aligned_close(self):
        if self.btc is None:
            return None
        b = self.btc.set_index("ts")["close"]
        return b.reindex(self.df["ts"]).ffill().reset_index(drop=True)

    @lru_cache(maxsize=None)
    def rel_dislocation(self, lookback, window):
        """Z-score of the coin's `lookback`-bar log return in excess of beta * BTC's."""
        b = self.btc_aligned_close()
        rc = np.log(self.c).diff()
        rb = np.log(b).diff()
        beta = (rc.rolling(window).cov(rb) / rb.rolling(window).var()).shift(1)
        resid = np.log(self.c).diff(lookback) - beta * np.log(b).diff(lookback)
        return ta.zscore(resid, window), np.log(b).diff(lookback)


def _sides(long_mask, short_mask, sides: str) -> np.ndarray:
    lm = np.asarray(long_mask, dtype=bool) if sides in ("long", "both") else False
    sm = np.asarray(short_mask, dtype=bool) if sides in ("short", "both") else False
    out = np.where(lm, 1, np.where(sm, -1, 0)).astype(np.int8)
    return out


def _atr_exits(f: Features, p: dict) -> dict:
    a = f.atr(14).to_numpy()
    out = {"tp_d": p.get("tp_atr", np.inf) * a, "sl_d": p["sl_atr"] * a}
    if p.get("tp1_atr"):
        out["tp1_d"] = p["tp1_atr"] * a
    return out


# --------------------------------------------------------------------------------------
# S1  Trend-Pullback RSI ("buy the dip in an up-trend, sell the rip in a down-trend")
# --------------------------------------------------------------------------------------
def trend_pullback_rsi(f: Features, p: dict) -> dict:
    r = f.rsi(p["rsi_n"])
    tr = f.trend(p["trend_n"], p.get("slope", 24))
    long_m = (tr == 1) & (r < p["rsi_lo"])
    short_m = (tr == -1) & (r > 100 - p["rsi_lo"])
    sig = {"side": _sides(long_m, short_m, p.get("sides", "both")), **_atr_exits(f, p)}
    if p.get("exit") == "sma":
        m = f.sma(p.get("exit_sma", 5))
        sig["dyn_long"] = (f.c > m).to_numpy()
        sig["dyn_short"] = (f.c < m).to_numpy()
    return sig


# --------------------------------------------------------------------------------------
# S2  Bollinger snap-back: close back inside the band after an extreme close outside it
# --------------------------------------------------------------------------------------
def bollinger_snapback(f: Features, p: dict) -> dict:
    lo, mid, up = f.bb(p.get("bb_n", 20), p["bb_k"])
    r = f.rsi(14)
    c = f.c
    long_m = (c.shift(1) < lo.shift(1)) & (c > lo) & (r.shift(1) < p.get("rsi_max", 30))
    short_m = (c.shift(1) > up.shift(1)) & (c < up) & (r.shift(1) > 100 - p.get("rsi_max", 30))
    tf = p.get("trend_filter")
    if tf:
        tr = f.trend(tf, 24)
        long_m &= tr != -1
        short_m &= tr != 1
    return {"side": _sides(long_m, short_m, p.get("sides", "both")), **_atr_exits(f, p)}


# --------------------------------------------------------------------------------------
# S3  Capitulation flush reversal (liquidation-cascade proxy: huge body + volume + one-sided
#     taker flow + close outside the band) -> fade for a quick bounce
# --------------------------------------------------------------------------------------
def capitulation_reversal(f: Features, p: dict) -> dict:
    df = f.df
    a = f.atr(14)
    body = df["close"] - df["open"]
    vr = f.vol_ratio(20)
    tbr = f.taker_buy_ratio()
    lo, _, up = f.bb(20, p.get("bb_k", 2.0))
    long_m = (-body > p["body_atr"] * a.shift(1)) & (vr > p["vol_mult"]) & (df["close"] < lo)
    short_m = (body > p["body_atr"] * a.shift(1)) & (vr > p["vol_mult"]) & (df["close"] > up)
    if p.get("tbr"):
        long_m &= tbr < p["tbr"]
        short_m &= tbr > 1 - p["tbr"]
    return {"side": _sides(long_m, short_m, p.get("sides", "both")), **_atr_exits(f, p)}


# --------------------------------------------------------------------------------------
# S4  Relative dislocation vs BTC: an alt dumps (pumps) far more than its BTC beta implies
#     while BTC itself is calm -> idiosyncratic over-reaction, fade it
# --------------------------------------------------------------------------------------
def btc_relative_dislocation(f: Features, p: dict) -> dict:
    z, btc_ret = f.rel_dislocation(p["lookback"], p.get("window", 500))
    calm = btc_ret.abs() < p["btc_calm"]
    long_m = (z < -p["z"]) & calm
    short_m = (z > p["z"]) & calm
    return {"side": _sides(long_m, short_m, p.get("sides", "both")), **_atr_exits(f, p)}


# --------------------------------------------------------------------------------------
# S5  Trend continuation pullback with TP1 scale-out + break-even stop (the structure most
#     Telegram channels use; "win" = trade closed with net profit)
# --------------------------------------------------------------------------------------
def trend_continuation(f: Features, p: dict) -> dict:
    e1, e2, e3 = f.ema(20), f.ema(50), f.ema(200)
    df = f.df
    r = f.rsi(14)
    up = (e1 > e2) & (e2 > e3)
    dn = (e1 < e2) & (e2 < e3)
    long_m = up & (df["low"] <= e1) & (df["close"] > e1) & (df["close"] > df["open"]) & (r < p.get("rsi_cap", 65))
    short_m = dn & (df["high"] >= e1) & (df["close"] < e1) & (df["close"] < df["open"]) & (r > 100 - p.get("rsi_cap", 65))
    if p.get("adx_min"):
        strong = f.adx(14) > p["adx_min"]
        long_m &= strong
        short_m &= strong
    return {"side": _sides(long_m, short_m, p.get("sides", "both")), **_atr_exits(f, p)}


# --------------------------------------------------------------------------------------
# S6  VWAP stretch: price stretched N ATRs from the rolling VWAP with a short-term RSI extreme
# --------------------------------------------------------------------------------------
def vwap_stretch(f: Features, p: dict) -> dict:
    v = f.vwap(p.get("vwap_n", 24))
    a = f.atr(14)
    dev = (f.c - v) / a
    r = f.rsi(p.get("rsi_n", 2))
    long_m = (dev < -p["dev"]) & (r < p.get("rsi_lo", 10))
    short_m = (dev > p["dev"]) & (r > 100 - p.get("rsi_lo", 10))
    tf = p.get("trend_filter")
    if tf:
        tr = f.trend(tf, 24)
        long_m &= tr != -1
        short_m &= tr != 1
    return {"side": _sides(long_m, short_m, p.get("sides", "both")), **_atr_exits(f, p)}


# --------------------------------------------------------------------------------------
# S7  Keltner wick-catcher (liquidity provision): once price is already stretched below the
#     EMA20 by `arm` ATR, quote a resting BUY LIMIT deeper at EMA20 - `dev` ATR (re-quoted every
#     bar, live for `valid` bars). Forced sellers / stop-runs print wicks into the bid; we exit
#     into the snap-back with a resting TP. Mirror for shorts.
# --------------------------------------------------------------------------------------
def keltner_wick_catcher(f: Features, p: dict) -> dict:
    m = f.ema(p.get("ema_n", 20))
    a = f.atr(14)
    long_m = f.c < m - p["arm"] * a
    short_m = f.c > m + p["arm"] * a
    if p.get("vol_cap"):  # skip when volatility is exploding (trend/crash regime)
        calm = (a / f.atr(200)) < p["vol_cap"]
        long_m &= calm
        short_m &= calm
    tf = p.get("trend_filter")
    if tf:
        tr = f.trend(tf, 24)
        long_m &= tr != -1
        short_m &= tr != 1
    side = _sides(long_m, short_m, p.get("sides", "both"))
    lim = np.where(side == 1, m - p["dev"] * a, np.where(side == -1, m + p["dev"] * a, np.nan))
    return {"side": side, "limit_px": lim, **_atr_exits(f, p)}


# --------------------------------------------------------------------------------------
# S8  RSI-2 extreme with a limit entry below the signal close (better price than market)
# --------------------------------------------------------------------------------------
def rsi_extreme_limit(f: Features, p: dict) -> dict:
    r = f.rsi(p.get("rsi_n", 2))
    a = f.atr(14)
    long_m = r < p["rsi_lo"]
    short_m = r > 100 - p["rsi_lo"]
    tf = p.get("trend_filter")
    if tf:
        tr = f.trend(tf, 24)
        long_m &= tr != -1
        short_m &= tr != 1
    side = _sides(long_m, short_m, p.get("sides", "both"))
    off = p["offset"] * a
    lim = np.where(side == 1, f.c - off, np.where(side == -1, f.c + off, np.nan))
    return {"side": side, "limit_px": lim, **_atr_exits(f, p)}


# --------------------------------------------------------------------------------------
# S9  Regime-gated pullback: S1's washout trigger, but only when BOTH the coin and the market
#     (BTC) are in the same-direction trend. Signals switch off in hostile regimes.
# --------------------------------------------------------------------------------------
@lru_cache(maxsize=None)
def _btc_trend(f: Features, n: int, slope: int) -> np.ndarray:
    if f.btc is None:
        return f.trend(n, slope)
    b = Features(f.btc)
    tr = pd.Series(b.trend(n, slope), index=f.btc["ts"])
    return tr.reindex(f.df["ts"]).ffill().fillna(0).to_numpy()


def regime_gated_pullback(f: Features, p: dict) -> dict:
    r = f.rsi(p.get("rsi_n", 3))
    n = p["trend_n"]
    coin = f.trend(n, p.get("slope", 24))
    mkt = _btc_trend(f, p.get("btc_trend_n", n), p.get("slope", 24))
    long_m = (coin == 1) & (mkt == 1) & (r < p["rsi_lo"])
    short_m = (coin == -1) & (mkt == -1) & (r > 100 - p["rsi_lo"])
    exits = _atr_exits(f, p)
    if p.get("max_sl_pct"):  # skip setups whose ATR stop would be wider than X% (post-crash vol)
        ok = exits["sl_d"] / f.c.to_numpy() * 100 <= p["max_sl_pct"]
        long_m &= ok
        short_m &= ok
    return {"side": _sides(long_m, short_m, p.get("sides", "both")), **exits}


# --------------------------------------------------------------------------------------
# S10 Liquidity sweep reversal ("turtle soup"): the bar runs the prior N-bar low (stops below
#     it get triggered), then closes back above it. Optional higher-timeframe trend alignment.
# --------------------------------------------------------------------------------------
def liquidity_sweep(f: Features, p: dict) -> dict:
    df = f.df
    n = p["lookback"]
    a = f.atr(14)
    prior_lo = df["low"].rolling(n).min().shift(1)
    prior_hi = df["high"].rolling(n).max().shift(1)
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    loc = (df["close"] - df["low"]) / rng
    long_m = (df["low"] < prior_lo) & (df["close"] > prior_lo) & (loc > p.get("loc", 0.6))
    short_m = (df["high"] > prior_hi) & (df["close"] < prior_hi) & (loc < 1 - p.get("loc", 0.6))
    if p.get("min_sweep_atr"):
        long_m &= (prior_lo - df["low"]) > p["min_sweep_atr"] * a
        short_m &= (df["high"] - prior_hi) > p["min_sweep_atr"] * a
    if p.get("trend_n"):
        coin = f.trend(p["trend_n"], 24)
        mkt = _btc_trend(f, p["trend_n"], 24)
        long_m &= (coin == 1) & (mkt == 1) if p.get("regime") else coin != -1
        short_m &= (coin == -1) & (mkt == -1) if p.get("regime") else coin != 1
    return {"side": _sides(long_m, short_m, p.get("sides", "both")), **_atr_exits(f, p)}


STRATEGIES = {
    "S10_liquidity_sweep": liquidity_sweep,
    "S1s_trend_pullback_sides": trend_pullback_rsi,
    "S9_regime_gated_pullback": regime_gated_pullback,
    "S7_keltner_wick_catcher": keltner_wick_catcher,
    "S8_rsi_extreme_limit": rsi_extreme_limit,
    "S1_trend_pullback_rsi": trend_pullback_rsi,
    "S2_bollinger_snapback": bollinger_snapback,
    "S3_capitulation_reversal": capitulation_reversal,
    "S4_btc_relative_dislocation": btc_relative_dislocation,
    "S5_trend_continuation_tp1": trend_continuation,
    "S6_vwap_stretch": vwap_stretch,
}
