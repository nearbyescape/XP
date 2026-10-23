"""Morning carry-over: night setups that are still valid, posted at the session's first check.

Signals whose candle closes outside the session are tracked unpublished (mode 'offhours'). At the first
check of the session day, each one still open and before TP1 is posted for members as a new signal row
(`carried_from` = the night signal): entry at the morning price (the open of the candle starting at that
check), the night setup's TP1 / TP2 / TP3 and stop unchanged, the same expiry, stop to the new entry
after TP1. Not carried: a coin that gets a new signal at that check, a second night setup on one coin
(the latest is kept), a morning price already outside stop..TP1, a strategy that is not live, and any
while publishing is paused. Strategy health (kill switch, win-rate watch) counts the night signal only.

2022-01 .. 2026-10 with these rules (live lifecycle and costs, 10 coins): 0.65 a day, win rate 78%,
PF 1.23; the channel goes from 2.44 to 3.09 signals a day and growth at 0.5% risk from +71% to +91%,
with the deepest fall from 10.7% to 17.2% (docs/crypto-signal-strategy-research.md §7).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from ..config import Settings
from ..core.risk import exposure
from ..core.session import Session
from ..models import Signal
from ..services import repo


async def carry_candidates(s, session: Session, close_t: datetime, new_coins: set[str]) -> list[Signal]:
    """Night setups to carry over at the check closing at `close_t` (none unless it is the day's first)."""
    opened = session.last_start(close_t)
    checks = session.checks(session.local(opened).date())
    if not checks or close_t != checks[0]:
        return []
    rows = (await s.scalars(select(Signal).where(
        Signal.published.is_(False), Signal.mode == "offhours", Signal.status == "ACTIVE",
        Signal.targets_hit == 0, Signal.carried_from.is_(None),
        Signal.entry_at >= session.last_end(opened), Signal.entry_at < opened).order_by(Signal.entry_at))).all()
    latest = {r.symbol: r for r in rows}  # the latest night setup per coin
    return [r for sym, r in latest.items() if sym not in new_coins]


async def carry_over(s, settings: Settings, close_t: datetime, night: list[Signal], prices: dict[str, float],
                     states: dict, telegram) -> list[Signal]:
    """Post the carry-overs; `prices` holds the morning entry price of each coin. Returns the new rows."""
    if (await repo.publishing(s)).get("paused"):
        return []
    made = []
    for n in night:
        st, entry = states.get(n.strategy), prices.get(n.symbol)
        row = await s.get(Signal, n.id)
        if (st is None or st.mode != "live" or st.auto_paused or entry is None or row is None
                or row.status != "ACTIVE" or row.targets_hit):
            continue
        if not min(row.stop_loss, row.take_profit) < entry < max(row.stop_loss, row.take_profit):
            continue  # the morning price is already past TP1 or the stop
        uid = f"{row.uid}:carry"
        if await s.scalar(select(Signal.id).where(Signal.uid == uid)):
            continue  # already carried (restart during the same check)
        sig = Signal(
            uid=uid, origin=row.origin, strategy=row.strategy, symbol=row.symbol, side=row.side,
            signal_open_at=row.signal_open_at, entry_at=close_t, expires_at=row.expires_at, entry_price=entry,
            take_profit=row.take_profit, stop_loss=row.stop_loss, targets=row.targets, breakeven=row.breakeven,
            stop_current=row.stop_loss, fills=[], targets_hit=0, atr=row.atr, tp_atr=row.tp_atr,
            sl_atr=row.sl_atr, max_bars=row.max_bars, regime_coin=row.regime_coin, regime_btc=row.regime_btc,
            model_prob=row.model_prob, model_version=row.model_version, mode="live", published=True,
            status="ACTIVE", last_price=entry, mfe=0.0, mae=0.0, carried_from=row.id)
        s.add(sig)
        await s.flush()
        sig.risk_at_entry = exposure(await repo.open_signals(s, published_only=True),
                                     settings.default_risk_pct).at_risk
        if telegram:
            await telegram.enqueue_signal_new(s, sig)
        await repo.log_event(s, "info", "signal.carried",
                             f"{sig.strategy} {'LONG' if sig.side == 1 else 'SHORT'} {sig.symbol} @ {entry:g} "
                             f"(night setup {row.id}, still valid)", {"signal_id": sig.id, "night_id": row.id})
        made.append(sig)
    return made
