"""Automatic strategy pause / resume (docs/crypto-signal-strategy-research.md §8).

Pause a live strategy when its last N closed signals show win rate < X or profit factor < Y.
While paused it keeps generating and tracking signals unpublished; it resumes once M signals
opened after the pause show profit factor > Z. An administrator can override either way.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import desc, select

from ..config import Settings
from ..core import stats
from ..models import Signal, StrategyState
from ..services import repo
from ..telegram import formatting as fmt

log = logging.getLogger(__name__)


def _rows(signals):
    return [{"exit_at": r.exit_at, "pnl_net": r.pnl_net, "r_multiple": r.r_multiple,
             "exit_reason": r.exit_reason} for r in signals]


async def review_strategy(s, code: str, settings: Settings, telegram, now: datetime) -> None:
    st = await s.get(StrategyState, code)
    if st is None or st.mode != "live":
        return
    if not st.auto_paused:
        last = (await s.scalars(select(Signal).where(Signal.strategy == code, Signal.status == "CLOSED",
                                                     Signal.origin != "backfill")
                                .order_by(desc(Signal.exit_at)).limit(settings.kill_switch_window))).all()
        if len(last) < settings.kill_switch_window:
            return
        h = stats.rolling_health(_rows(last))
        pf = h["profit_factor"] if h["profit_factor"] is not None else float("inf")
        if h["win_rate"] < settings.kill_switch_min_win_rate or pf < settings.kill_switch_min_profit_factor:
            st.auto_paused, st.paused_at = True, now
            st.pause_reason = (f"last {h['signals']} signals: win rate {h['win_rate'] * 100:.1f}% "
                               f"(min {settings.kill_switch_min_win_rate * 100:.0f}%), profit factor "
                               f"{pf:.2f} (min {settings.kill_switch_min_profit_factor:.2f})")
            await repo.log_event(s, "warning", "strategy.paused", f"{code} auto-paused: {st.pause_reason}")
            if telegram:
                await telegram.enqueue_notice(
                    s, f"⏸ <b>{code} paused</b> — rolling performance dropped below its safety limits. "
                       f"It keeps running in paper mode and resumes automatically after recovering.")
                await telegram.enqueue_admin(s, fmt.alert(settings.app_name, "warning", "strategy.paused",
                                                          f"{code} auto-paused: {st.pause_reason}"))
            log.warning("%s auto-paused: %s", code, st.pause_reason)
        return
    since = (await s.scalars(select(Signal).where(Signal.strategy == code, Signal.status == "CLOSED",
                                                  Signal.origin != "backfill", Signal.entry_at >= st.paused_at)
                             .order_by(desc(Signal.exit_at)))).all()
    if len(since) < settings.kill_switch_resume_after:
        return
    h = stats.rolling_health(_rows(since))
    if (h["profit_factor"] or 0) > settings.kill_switch_resume_profit_factor:
        st.auto_paused, st.pause_reason, st.paused_at = False, None, None
        await repo.log_event(s, "info", "strategy.resumed",
                             f"{code} resumed after {h['signals']} paper signals (PF {h['profit_factor']:.2f})")
        if telegram:
            await telegram.enqueue_notice(s, f"▶️ <b>{code} resumed</b> after recovering in paper mode.")
            await telegram.enqueue_admin(s, fmt.alert(settings.app_name, "info", "strategy.resumed",
                                                      f"{code} resumed after {h['signals']} paper signals "
                                                      f"(PF {h['profit_factor']:.2f})"))
