"""Static description of the three validated strategies (docs/crypto-signal-strategy-research.md).

Parameters are the centre of the out-of-sample plateau. Do not tune them live: any change must
go through the research harness first.
"""

from __future__ import annotations

from dataclasses import dataclass, field

INTERVAL = "4h"
BAR_SECONDS = 4 * 3600


@dataclass(frozen=True)
class StrategySpec:
    code: str
    letter: str
    name: str
    kind: str
    priority: int                 # lower wins when two strategies fire on the same coin/candle
    tp_atr: float
    sl_atr: float
    max_bars: int
    params: dict = field(default_factory=dict)
    summary: str = ""
    rules: str = ""
    benchmark: dict = field(default_factory=dict)  # out-of-sample backtest, 10 coins, net of costs


RGP = StrategySpec(
    code="RGP-4H", letter="A", name="Regime Pullback", kind="rules", priority=1,
    tp_atr=0.5, sl_atr=4.0, max_bars=48,
    params={"rsi_n": 2, "rsi_lo": 5, "trend_n": 200, "slope": 24},
    summary=("Fades a 2-period RSI washout only in the direction of a trend shared by the coin "
             "and BTC: forced selling inside a trend, not the start of a reversal."),
    rules=("LONG  if coin trend UP and BTC trend UP and RSI(2) < 5\n"
           "SHORT if coin trend DOWN and BTC trend DOWN and RSI(2) > 95\n"
           "trend UP = close > EMA200 and EMA200 rising over 24 candles (DOWN mirrored)\n"
           "TP 0.5 x ATR(14) · SL 4.0 x ATR(14) · time stop 48 candles (8 days)"),
    benchmark={"period": "2022-01 → 2026-10", "signals": 1800, "win_rate": 0.905,
               "breakeven_win_rate": 0.880, "profit_factor": 1.30, "net_pct": 0.24,
               "avg_win_pct": 1.15, "avg_loss_pct": 8.40},
)

RSR = StrategySpec(
    code="RSR-4H", letter="B", name="Sweep Reversal", kind="rules", priority=2,
    tp_atr=0.5, sl_atr=3.0, max_bars=24,
    params={"lookback": 24, "loc": 0.5, "trend_n": 200, "slope": 24},
    summary=("A liquidity sweep: price runs the 4-day low (triggering resting stops) and closes "
             "back above it, while the coin and BTC trend the same way."),
    rules=("LONG  if low < lowest low of prior 24 candles, close back above it,\n"
           "close in the upper half of the candle, coin and BTC trend UP\n"
           "SHORT mirrored on the 24-candle high, coin and BTC trend DOWN\n"
           "TP 0.5 x ATR(14) · SL 3.0 x ATR(14) · time stop 24 candles (4 days)"),
    benchmark={"period": "2022-01 → 2026-10", "signals": 947, "win_rate": 0.883,
               "breakeven_win_rate": 0.837, "profit_factor": 1.47, "net_pct": 0.32,
               "avg_win_pct": 1.12, "avg_loss_pct": 5.74},
)

MLR = StrategySpec(
    code="MLR-4H", letter="C", name="ML-Ranked", kind="model", priority=3,
    tp_atr=0.5, sl_atr=3.0, max_bars=24,
    params={"max_per_candle": 5},
    summary=("A LightGBM model scores every coin, both directions, at every 4h close for the "
             "probability that a 0.5 ATR target is hit before a 3 ATR stop. Only its most "
             "confident calls (top 5% of its training-period scores) are published."),
    rules=("score = P(TP before SL within 24 candles | 48 features)\n"
           "signal if score >= model threshold (≈0.88–0.91), best 5 per candle\n"
           "TP 0.5 x ATR(14) · SL 3.0 x ATR(14) · time stop 24 candles (4 days)\n"
           "retrained quarterly on an expanding window"),
    benchmark={"period": "2022-01 → 2026-10 (walk-forward)", "signals": 3240, "win_rate": 0.887,
               "breakeven_win_rate": 0.838, "profit_factor": 1.52, "net_pct": 0.41,
               "avg_win_pct": 1.34, "avg_loss_pct": 6.89},
)

STRATEGIES: dict[str, StrategySpec] = {s.code: s for s in (RGP, RSR, MLR)}
BOOK_BENCHMARK = {"period": "2022-01 → 2026-10", "signals": 5829, "win_rate": 0.891,
                  "breakeven_win_rate": 0.852, "profit_factor": 1.42, "net_pct": 0.33,
                  "avg_win_pct": 1.24, "avg_loss_pct": 7.14, "cagr_at_half_pct_risk": 0.162,
                  "max_dd_at_half_pct_risk": 0.138}
