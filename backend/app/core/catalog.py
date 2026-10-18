"""Static description of the three validated strategies (docs/crypto-signal-strategy-research.md).

Parameters are the centre of the out-of-sample plateau. Do not tune them live: any change must
go through the research harness first.
"""

from __future__ import annotations

from dataclasses import dataclass, field

INTERVAL = "4h"
BAR_SECONDS = 4 * 3600

# Exit plan for every strategy (research/tp_ladder.py): TP1 / TP2 / TP3 at 0.5 / 1.0 / 1.5 x ATR close
# 50% / 30% / 20% of the position; after TP1 the stop moves to the entry price. TP1 is the validated
# target, so the win rate is unchanged: a signal that reaches TP1 ends at or above break-even.
# Benchmarks below: research/results/tp_ladder_1h.md (out-of-sample 2022 → Oct 2026, 1h paths).
TARGETS_ATR = (0.5, 1.0, 1.5)
TARGET_SIZES = (0.5, 0.3, 0.2)


@dataclass(frozen=True)
class StrategySpec:
    code: str
    letter: str
    name: str
    kind: str
    priority: int                 # lower wins when two strategies fire on the same coin/candle
    tp_atr: float                 # TP1 (the validated target)
    sl_atr: float
    max_bars: int
    params: dict = field(default_factory=dict)
    targets_atr: tuple[float, ...] = TARGETS_ATR
    target_sizes: tuple[float, ...] = TARGET_SIZES
    breakeven: bool = True        # stop to entry after TP1
    summary: str = ""
    rules: str = ""
    basis: str = ""               # one line for the signal message: what the setup is built on
    benchmark: dict = field(default_factory=dict)  # out-of-sample backtest, 10 coins, net of costs, TP1/2/3 plan


RGP = StrategySpec(
    code="RGP-4H", letter="A", name="Regime Pullback", kind="rules", priority=1,
    tp_atr=0.5, sl_atr=4.0, max_bars=48,
    params={"rsi_n": 2, "rsi_lo": 5, "trend_n": 200, "slope": 24},
    basis="RSI(2) washout · EMA200 trend · ATR14 · completed 4H candle",
    summary=("Fades a 2-period RSI washout only in the direction of a trend shared by the coin "
             "and BTC: forced selling inside a trend, not the start of a reversal."),
    rules=("LONG  if coin trend UP and BTC trend UP and RSI(2) < 5\n"
           "SHORT if coin trend DOWN and BTC trend DOWN and RSI(2) > 95\n"
           "trend UP = close > EMA200 and EMA200 rising over 24 candles (DOWN mirrored)\n"
           "TP1 / TP2 / TP3 at 0.5 / 1.0 / 1.5 x ATR(14), closing 50 / 30 / 20%\n"
           "SL 4.0 x ATR(14), moved to entry after TP1 · time stop 48 candles (8 days)"),
    benchmark={"period": "2022-01 → 2026-10", "signals": 1798, "win_rate": 0.905,
               "breakeven_win_rate": 0.884, "profit_factor": 1.26, "net_pct": 0.20,
               "avg_win_pct": 1.10, "avg_loss_pct": 8.37, "tp1_rate": 0.905, "tp2_rate": 0.429, "tp3_rate": 0.279},
)

RSR = StrategySpec(
    code="RSR-4H", letter="B", name="Sweep Reversal", kind="rules", priority=2,
    tp_atr=0.5, sl_atr=3.0, max_bars=24,
    params={"lookback": 24, "loc": 0.5, "trend_n": 200, "slope": 24},
    basis="Liquidity sweep · EMA200 trend · ATR14 · completed 4H candle",
    summary=("A liquidity sweep: price runs the 4-day low (triggering resting stops) and closes "
             "back above it, while the coin and BTC trend the same way."),
    rules=("LONG  if low < lowest low of prior 24 candles, close back above it,\n"
           "close in the upper half of the candle, coin and BTC trend UP\n"
           "SHORT mirrored on the 24-candle high, coin and BTC trend DOWN\n"
           "TP1 / TP2 / TP3 at 0.5 / 1.0 / 1.5 x ATR(14), closing 50 / 30 / 20%\n"
           "SL 3.0 x ATR(14), moved to entry after TP1 · time stop 24 candles (4 days)"),
    benchmark={"period": "2022-01 → 2026-10", "signals": 943, "win_rate": 0.883,
               "breakeven_win_rate": 0.835, "profit_factor": 1.49, "net_pct": 0.33,
               "avg_win_pct": 1.14, "avg_loss_pct": 5.78, "tp1_rate": 0.883, "tp2_rate": 0.444, "tp3_rate": 0.321},
)

MLR = StrategySpec(
    code="MLR-4H", letter="C", name="ML-Ranked", kind="model", priority=3,
    tp_atr=0.5, sl_atr=3.0, max_bars=24,
    params={"max_per_candle": 5},
    basis="LightGBM model · 48 features · ATR14 · completed 4H candle",
    summary=("A LightGBM model scores every coin, both directions, at every 4h close for the "
             "probability that a 0.5 ATR target is hit before a 3 ATR stop. Only its most "
             "confident calls (top 5% of its training-period scores) are published."),
    rules=("score = P(TP1 before SL within 24 candles | 48 features)\n"
           "signal if score >= model threshold (≈0.88–0.91), best 5 per candle\n"
           "TP1 / TP2 / TP3 at 0.5 / 1.0 / 1.5 x ATR(14), closing 50 / 30 / 20%\n"
           "SL 3.0 x ATR(14), moved to entry after TP1 · time stop 24 candles (4 days)\n"
           "retrained quarterly on an expanding window"),
    benchmark={"period": "2022-01 → 2026-10 (walk-forward)", "signals": 3236, "win_rate": 0.889,
               "breakeven_win_rate": 0.834, "profit_factor": 1.59, "net_pct": 0.45,
               "avg_win_pct": 1.36, "avg_loss_pct": 6.83, "tp1_rate": 0.888, "tp2_rate": 0.463, "tp3_rate": 0.311},
)

STRATEGIES: dict[str, StrategySpec] = {s.code: s for s in (RGP, RSR, MLR)}
BOOK_BENCHMARK = {"period": "2022-01 → 2026-10", "signals": 5788, "win_rate": 0.893,
                  "breakeven_win_rate": 0.851, "profit_factor": 1.46, "net_pct": 0.35,
                  "avg_win_pct": 1.24, "avg_loss_pct": 7.12, "cagr_at_half_pct_risk": 0.173,
                  "max_dd_at_half_pct_risk": 0.142, "tp1_rate": 0.892, "tp2_rate": 0.451, "tp3_rate": 0.304}
