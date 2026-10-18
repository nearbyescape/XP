"""Signal lifecycle: fills, take-profit / stop / time exits, P&L in % and R.

Same conventions as the research backtest engine (research/backtest/engine.py):
* entry = open of the candle that starts at the signal candle's close (market order)
* TP / SL are resting orders; if both are touched inside one candle the STOP is assumed first
* after the entry candle, a candle that opens beyond a level fills at its open (gap)
* time stop: exit at the close of the candle that ends at `expires_at`
Works on any candle resolution: 1m candles live, 4h candles in replays and tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Bar:
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass
class Costs:
    entry: float = 0.0007
    tp: float = 0.0002
    exit: float = 0.0008


@dataclass
class TradeState:
    side: int
    entry_price: float
    take_profit: float
    stop_loss: float
    entry_at: datetime
    expires_at: datetime
    last_checked_at: datetime | None = None   # close time of the last processed bar
    mfe: float = 0.0                          # best excursion, fraction of entry
    mae: float = 0.0                          # worst excursion, fraction of entry (<= 0)
    last_price: float | None = None
    exit_price: float | None = None
    exit_at: datetime | None = None
    exit_reason: str | None = None            # TP | SL | TIME

    @property
    def closed(self) -> bool:
        return self.exit_reason is not None


def levels(side: int, entry: float, atr: float, tp_atr: float, sl_atr: float) -> tuple[float, float]:
    return entry + side * tp_atr * atr, entry - side * sl_atr * atr


def step(st: TradeState, bar: Bar) -> bool:
    """Process one CLOSED bar. Returns True if the trade closed on it."""
    if st.closed or bar.open_time < st.entry_at:
        return st.closed
    if st.last_checked_at is not None and bar.close_time <= st.last_checked_at:
        return False  # already processed
    first = bar.open_time == st.entry_at
    s = st.side
    px = reason = None
    if s == 1:
        if not first and bar.open <= st.stop_loss:
            px, reason = bar.open, "SL"
        elif not first and bar.open >= st.take_profit:
            px, reason = bar.open, "TP"
        elif bar.low <= st.stop_loss:
            px, reason = st.stop_loss, "SL"
        elif bar.high >= st.take_profit:
            px, reason = st.take_profit, "TP"
        fav, adv = bar.high / st.entry_price - 1, bar.low / st.entry_price - 1
    else:
        if not first and bar.open >= st.stop_loss:
            px, reason = bar.open, "SL"
        elif not first and bar.open <= st.take_profit:
            px, reason = bar.open, "TP"
        elif bar.high >= st.stop_loss:
            px, reason = st.stop_loss, "SL"
        elif bar.low <= st.take_profit:
            px, reason = st.take_profit, "TP"
        fav, adv = 1 - bar.low / st.entry_price, 1 - bar.high / st.entry_price
    if reason is None and bar.close_time >= st.expires_at:
        px, reason = bar.close, "TIME"
    if reason is not None:
        # the path inside the exit bar is unknown: only the realised exit counts as an excursion
        fav = adv = s * (px / st.entry_price - 1)
    st.mfe = max(st.mfe, fav)
    st.mae = min(st.mae, adv)
    st.last_checked_at = bar.close_time
    st.last_price = bar.close if reason is None else px
    if reason is not None:
        st.exit_price, st.exit_at, st.exit_reason = px, bar.close_time, reason
        return True
    return False


def pnl(st: TradeState, costs: Costs) -> dict:
    """Gross / net return (fraction of notional) and R multiple (net / planned stop distance)."""
    gross = st.side * (st.exit_price / st.entry_price - 1)
    net = gross - costs.entry - (costs.tp if st.exit_reason == "TP" else costs.exit)
    risk = abs(st.entry_price - st.stop_loss) / st.entry_price
    return {"gross": gross, "net": net, "r": net / risk if risk > 0 else 0.0}


def unrealised(side: int, entry: float, price: float) -> float:
    return side * (price / entry - 1)
