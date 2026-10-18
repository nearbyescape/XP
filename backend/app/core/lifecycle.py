"""Signal lifecycle: fills, take-profit / stop / time exits, P&L in % and R.

Same conventions as the research backtest engine (research/backtest/engine.py):
* entry = open of the candle that starts at the signal candle's close (market order)
* TP / SL are resting orders; if both are touched inside one candle the STOP is assumed first
* after the entry candle, a candle that opens beyond a level fills at its open (gap)
* time stop: exit at the close of the candle that ends at `expires_at`
Works on any candle resolution: 1m candles live, 4h candles in replays and tests.

Multiple targets (research/tp_ladder.py): TP1..TPn each close a fixed fraction of the position,
in order. With `breakeven`, the stop moves to the entry price once TP1 has filled. Inside the
candle that fills TP1 only its close is known to come after the fill: if that close is back beyond
the entry, the break-even stop was crossed and the rest exits at entry. A trade stopped after TP1
exits as "BE"; one that fills every target exits as "TP". Without explicit targets a trade has
one target, `take_profit`, for the whole position.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    take_profit: float                        # TP1
    stop_loss: float                          # stop in force (moves to entry after TP1 with breakeven)
    entry_at: datetime
    expires_at: datetime
    last_checked_at: datetime | None = None   # close time of the last processed bar
    mfe: float = 0.0                          # best excursion, fraction of entry
    mae: float = 0.0                          # worst excursion, fraction of entry (<= 0)
    last_price: float | None = None
    exit_price: float | None = None           # exit of the last part of the position
    exit_at: datetime | None = None
    exit_reason: str | None = None            # TP | SL | BE | TIME
    targets: tuple[float, ...] = ()           # target prices, TP1 first; () = take_profit only
    sizes: tuple[float, ...] = ()             # fraction of the position closed at each target
    breakeven: bool = False
    initial_stop: float | None = None         # planned stop; R is measured against it
    fills: list[tuple[datetime, float]] = field(default_factory=list)  # (bar close, price) per filled target

    def __post_init__(self) -> None:
        if not self.targets:
            self.targets, self.sizes = (self.take_profit,), (1.0,)
        if self.initial_stop is None:
            self.initial_stop = self.stop_loss

    @property
    def closed(self) -> bool:
        return self.exit_reason is not None

    @property
    def targets_hit(self) -> int:
        return len(self.fills)

    @property
    def remaining(self) -> float:
        return max(0.0, 1.0 - sum(self.sizes[:len(self.fills)]))


def levels(side: int, entry: float, atr: float, tp_atr: float, sl_atr: float) -> tuple[float, float]:
    return entry + side * tp_atr * atr, entry - side * sl_atr * atr


def target_prices(side: int, entry: float, atr: float, targets_atr: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(entry + side * k * atr for k in targets_atr)


def step(st: TradeState, bar: Bar) -> bool:
    """Process one CLOSED bar. Returns True if the trade closed on it."""
    if st.closed or bar.open_time < st.entry_at:
        return st.closed
    if st.last_checked_at is not None and bar.close_time <= st.last_checked_at:
        return False  # already processed
    first = bar.open_time == st.entry_at
    s = st.side
    beyond = (lambda price, level: price >= level) if s == 1 else (lambda price, level: price <= level)
    below = (lambda price, level: price <= level) if s == 1 else (lambda price, level: price >= level)
    best, worst = (bar.high, bar.low) if s == 1 else (bar.low, bar.high)
    stop = st.stop_loss  # the stop in force when the bar opened
    stop_reason = "BE" if st.fills and st.breakeven else "SL"
    filled_before = len(st.fills)
    px = reason = None

    def fill_targets(price_of) -> None:
        while len(st.fills) < len(st.targets):
            price = price_of(st.targets[len(st.fills)])
            if price is None:
                return
            st.fills.append((bar.close_time, price))

    if not first and below(bar.open, stop):
        px, reason = bar.open, stop_reason                              # gap through the stop
    else:
        if not first:                                                   # targets gapped at the open
            fill_targets(lambda lv: bar.open if beyond(bar.open, lv) else None)
        if len(st.fills) == len(st.targets):
            px, reason = st.fills[-1][1], "TP"
        elif below(worst, stop):
            px, reason = stop, stop_reason                              # stop first inside the bar
        else:
            fill_targets(lambda lv: lv if beyond(best, lv) else None)
            if len(st.fills) == len(st.targets):
                px, reason = st.fills[-1][1], "TP"
    if reason is None and st.breakeven and filled_before == 0 and st.fills and below(bar.close, st.entry_price):
        px, reason = st.entry_price, "BE"  # TP1 then back through the entry inside this candle
    if reason is None and bar.close_time >= st.expires_at:
        px, reason = bar.close, "TIME"

    fav, adv = s * (best / st.entry_price - 1), s * (worst / st.entry_price - 1)
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
    if st.breakeven and filled_before == 0 and st.fills:
        st.stop_loss = st.entry_price
    return False


def pnl(st: TradeState, costs: Costs) -> dict:
    """Gross / net return (fraction of notional) and R multiple (net / planned stop distance)."""
    sizes = st.sizes[:len(st.fills)]
    filled = sum(sizes)
    gross = sum(z * st.side * (price / st.entry_price - 1) for z, (_, price) in zip(sizes, st.fills, strict=True))
    net = gross - costs.entry - filled * costs.tp
    rest = 1.0 - filled
    if rest > 1e-9 and st.exit_price is not None:
        part = st.side * (st.exit_price / st.entry_price - 1)
        gross += rest * part
        net += rest * (part - costs.exit)
    risk = abs(st.entry_price - st.initial_stop) / st.entry_price
    return {"gross": gross, "net": net, "r": net / risk if risk > 0 else 0.0}


def unrealised(side: int, entry: float, price: float) -> float:
    return side * (price / entry - 1)
