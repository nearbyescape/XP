"""'Setup forming' note in the channel when the AI model is close to a signal.

At one of the session day's first checks (two or more still follow that day), when nothing has been
published yet that day, strategy C is live, publishing is not paused and C's best score is within
WATCH_SCORE_MARGIN of its threshold: one silent note to the channel, at most once a day. Over 2022 -
Sep 2026 (walk-forward scores, margin 0.005, the 09:30 and 13:30 IST checks) it would have gone out on
249 days, 1.0 a week; a signal followed later that day 69% of the time (39% on comparable days without
it) and the first one went the way the note leaned 77% of the time.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from ..config import Settings
from ..core.session import Session
from ..models import Signal
from ..services import repo
from ..telegram import formatting as fmt

STATE_KEY = "setup_forming"


async def review_forming(s, settings: Settings, session: Session, telegram, close_t: datetime,
                         scores: list[tuple[str, int, float]], threshold: float, c_state) -> bool:
    """Queue the note if every condition holds at the check closing at `close_t`. True when queued."""
    if not (settings.telegram_watch_messages and telegram and telegram.enabled and scores):
        return False
    if c_state is None or c_state.mode != "live" or c_state.auto_paused or not session.contains(close_t):
        return False
    opened = session.last_start(close_t)
    day = session.local(opened).date()
    checks = session.checks(day)
    if close_t not in checks or checks.index(close_t) > len(checks) - 3:
        return False  # too late in the day for a signal to follow
    if (await repo.publishing(s)).get("paused") or (await repo.get_state(s, STATE_KEY, {})).get("day") == str(day):
        return False
    symbol, side, prob = max(scores, key=lambda x: x[2])
    if prob < threshold - settings.watch_score_margin:
        return False
    if await s.scalar(select(func.count()).select_from(Signal).where(
            Signal.published.is_(True), Signal.entry_at >= opened, Signal.entry_at <= close_t)):
        return False  # the channel already has signals today
    later = checks[checks.index(close_t) + 1:]
    await telegram.enqueue_watch(s, fmt.setup_forming(side, close_t, later, telegram.style))
    await repo.set_state(s, STATE_KEY, {"day": str(day), "at": close_t.isoformat(), "symbol": symbol,
                                        "side": side, "score": round(prob, 4)})
    return True
