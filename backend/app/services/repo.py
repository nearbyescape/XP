"""Data access shared by the engine, the API and the bot."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

import pandas as pd
from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.lifecycle import TradeState
from ..db import upsert
from ..market.base import Kline
from ..models import Candle, EngineEvent, Signal, StrategyState, SystemState, utcnow

CANDLE_COLS = ["open", "high", "low", "close", "volume", "quote_volume", "trades",
               "taker_buy_base", "taker_buy_quote"]


# --- candles -------------------------------------------------------------------------------
async def latest_candle_time(s: AsyncSession, symbol: str, interval: str) -> datetime | None:
    return await s.scalar(select(func.max(Candle.open_time))
                          .where(Candle.symbol == symbol, Candle.interval == interval))


async def upsert_candles(s: AsyncSession, symbol: str, interval: str, klines: Iterable[Kline]) -> int:
    rows = [k.as_row(symbol, interval) for k in klines]
    for i in range(0, len(rows), 500):  # SQLite caps bound parameters per statement
        await upsert(s, Candle.__table__, rows[i:i + 500], ["symbol", "interval", "open_time"], CANDLE_COLS)
    return len(rows)


async def load_frame(s: AsyncSession, symbol: str, interval: str, since: datetime | None = None,
                     limit: int | None = None) -> pd.DataFrame:
    cols = [Candle.open_time, *(getattr(Candle, c) for c in CANDLE_COLS)]
    q = select(*cols).where(Candle.symbol == symbol, Candle.interval == interval)
    if since is not None:
        q = q.where(Candle.open_time >= since)
    q = q.order_by(desc(Candle.open_time)) if limit else q.order_by(Candle.open_time)
    if limit:
        q = q.limit(limit)
    rows = (await s.execute(q)).all()
    if limit:
        rows = rows[::-1]
    df = pd.DataFrame(rows, columns=["ts", *CANDLE_COLS])
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


# --- signals -------------------------------------------------------------------------------
async def open_signals(s: AsyncSession, published_only: bool = False) -> list[Signal]:
    q = select(Signal).where(Signal.status == "ACTIVE")
    if published_only:
        q = q.where(Signal.published.is_(True))
    return list((await s.scalars(q.order_by(Signal.entry_at))).all())


async def positions_open_at(s: AsyncSession, t: datetime) -> set[tuple[str, str]]:
    """(strategy, symbol) pairs that still hold the coin at time t: neither exited nor at TP1 by t.

    A signal frees its coin when it closes or reaches TP1 (the rest of the position then runs with
    the stop at entry), which is exactly when the validated single-target trade ends. Using "as of t"
    (not just status) keeps the rule exact even when the tracker has already processed later candles
    (demo catch-up, restarts)."""
    rows = await s.execute(select(Signal.strategy, Signal.symbol).where(
        Signal.entry_at <= t, (Signal.status == "ACTIVE") | (Signal.exit_at > t),
        Signal.tp1_at.is_(None) | (Signal.tp1_at > t)))
    return {(a, b) for a, b in rows.all()}


# --- signal <-> trade state ----------------------------------------------------------------
def trade_state(sig: Signal) -> TradeState:
    targets = sig.targets or []
    return TradeState(
        sig.side, sig.entry_price, sig.take_profit, sig.stop_current or sig.stop_loss, sig.entry_at,
        sig.expires_at, sig.last_checked_at, sig.mfe or 0.0, sig.mae or 0.0, sig.last_price,
        targets=tuple(p for p, _ in targets), sizes=tuple(z for _, z in targets),
        breakeven=bool(sig.breakeven), initial_stop=sig.stop_loss,
        fills=[(datetime.fromisoformat(t), px) for t, px in (sig.fills or [])])


def store_progress(row: Signal, st: TradeState) -> None:
    """Copy tracking progress (excursions, target fills, moved stop) onto the row."""
    row.last_checked_at, row.mfe, row.mae, row.last_price = st.last_checked_at, st.mfe, st.mae, st.last_price
    row.fills = [[t.isoformat(), px] for t, px in st.fills]
    row.targets_hit = st.targets_hit
    row.tp1_at = st.fills[0][0] if st.fills else None
    row.stop_current = st.stop_loss


async def closed_signals(s: AsyncSession, strategy: str | None = None, published_only: bool = True,
                         since: datetime | None = None, origin: str | None = None,
                         limit: int | None = None) -> list[Signal]:
    q = select(Signal).where(Signal.status == "CLOSED")
    if strategy:
        q = q.where(Signal.strategy == strategy)
    if published_only:
        q = q.where(Signal.published.is_(True))
    if since:
        q = q.where(Signal.exit_at >= since)
    if origin:
        q = q.where(Signal.origin == origin)
    q = q.order_by(desc(Signal.exit_at))
    if limit:
        q = q.limit(limit)
    return list((await s.scalars(q)).all())


# --- strategy state ------------------------------------------------------------------------
async def ensure_strategy_states(s: AsyncSession, defaults: dict[str, str]) -> None:
    existing = {r.code for r in (await s.scalars(select(StrategyState))).all()}
    for code, mode in defaults.items():
        if code not in existing:
            s.add(StrategyState(code=code, mode=mode, auto_paused=False))
    await s.commit()


async def strategy_states(s: AsyncSession) -> dict[str, StrategyState]:
    return {r.code: r for r in (await s.scalars(select(StrategyState))).all()}


# --- system state / events -----------------------------------------------------------------
async def get_state(s: AsyncSession, key: str, default=None):
    row = await s.get(SystemState, key)
    return row.value if row else default


async def set_state(s: AsyncSession, key: str, value) -> None:
    await upsert(s, SystemState.__table__, [{"key": key, "value": value, "updated_at": utcnow()}],
                 ["key"], ["value", "updated_at"])


async def publishing(s: AsyncSession) -> dict:
    """{"paused": bool, "by": str, "at": iso} — the administrator's pause of all new signals."""
    return await get_state(s, "publishing", {}) or {}


async def log_event(s: AsyncSession, level: str, kind: str, message: str, data: dict | None = None) -> None:
    s.add(EngineEvent(level=level, kind=kind, message=message, data=data, ts=utcnow()))


async def mark_signal(s: AsyncSession, signal_id: int, **values) -> None:
    values["updated_at"] = utcnow()
    await s.execute(update(Signal).where(Signal.id == signal_id).values(**values))
