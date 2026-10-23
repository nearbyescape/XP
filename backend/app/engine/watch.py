"""Early warnings for administrators (docs/deployment.md §Risk guard).

Measures, all on published signals:
  drawdown        - the published book below its peak, compounding every signal at the default risk
  win_rate:<code> - each strategy's last N closed signals
  concentration   - signals before TP1 in one direction (if their stops hit together)

An alert goes to the admin chats when a measure enters the watch or critical level and once more
when it is back to normal. Nothing is paused automatically: the administrator decides (/pause).
"""

from __future__ import annotations

import logging

from sqlalchemy import desc, select

from ..config import Settings
from ..core import stats
from ..core.catalog import STRATEGIES
from ..core.risk import classify, exposure, rank
from ..models import Signal, utcnow
from ..services import repo
from ..telegram import formatting as fmt

log = logging.getLogger(__name__)
STATE_KEY = "risk_watch"
TESTED_DRAWDOWN = 17.2  # % — worst fall from a peak of the published book in 2022-2026 testing
TESTED_WIN_RATE = 57    # % — worst 30-signal win rate of any strategy in testing


def _rows(signals):
    return [{"exit_at": r.exit_at, "pnl_net": r.pnl_net, "r_multiple": r.r_multiple,
             "exit_reason": r.exit_reason} for r in signals]


async def measures(s, settings: Settings, previous: dict) -> dict[str, dict]:
    """Current value, level and alert text of every measure."""
    risk = settings.default_risk_pct
    book = (await s.scalars(select(Signal).where(Signal.status == "CLOSED", Signal.published.is_(True),
                                                 Signal.origin.in_(["live", "demo"])))).all()
    out = {}

    dd = stats.equity_curve(_rows(book), risk / 100)["points"]
    dd_pct = dd[-1]["drawdown"] * 100 if dd else 0.0
    lvl = classify(dd_pct, settings.watch_drawdown_pct, settings.watch_drawdown_critical_pct,
                   previous.get("drawdown"), margin=2.0)
    out["drawdown"] = {
        "label": "Fall from peak", "value": round(dd_pct, 2), "unit": "%", "level": lvl,
        "watch": settings.watch_drawdown_pct, "critical": settings.watch_drawdown_critical_pct,
        "text": (f"Published signals are {dd_pct:.1f}% below their peak (at {risk:g}% risk per signal). "
                 + (f"That is deeper than anything in 2022-2026 testing ({TESTED_DRAWDOWN}%). "
                    "Consider /pause until you have reviewed." if lvl == "critical" else
                    f"Watch level {settings.watch_drawdown_pct:g}%; the worst in testing was {TESTED_DRAWDOWN}%.")),
    }

    n = settings.watch_win_rate_window
    for code in STRATEGIES:
        last = (await s.scalars(select(Signal).where(Signal.strategy == code, Signal.status == "CLOSED",
                                                     Signal.published.is_(True), Signal.carried_from.is_(None),
                                                     Signal.origin.in_(["live", "demo"]))
                                .order_by(desc(Signal.exit_at)).limit(n))).all()
        key = f"win_rate:{code}"
        if len(last) < n:
            out[key] = {"label": f"{code} last {n}", "value": None, "unit": "%", "level": None,
                        "watch": settings.watch_win_rate * 100, "critical": settings.watch_win_rate_critical * 100,
                        "text": f"{code}: {len(last)} of {n} signals closed so far"}
            continue
        wins = sum(1 for r in last if (r.pnl_net or 0) > 0)
        wr = wins / n * 100
        lvl = classify(wr, settings.watch_win_rate * 100, settings.watch_win_rate_critical * 100,
                       previous.get(key), margin=5.0, higher_is_worse=False)
        out[key] = {
            "label": f"{code} last {n}", "value": round(wr, 1), "unit": "%", "level": lvl,
            "watch": settings.watch_win_rate * 100, "critical": settings.watch_win_rate_critical * 100,
            "text": (f"{code} won {wins} of its last {n} signals ({wr:.0f}%). "
                     + (f"That is below the worst 30-signal stretch in testing ({TESTED_WIN_RATE}%). "
                        "Consider switching it to shadow on the admin page." if lvl == "critical" else
                        f"Watch level {settings.watch_win_rate * 100:.0f}%; the lowest stretch in testing was "
                        f"{TESTED_WIN_RATE}%.")),
        }

    exp = exposure(await repo.open_signals(s, published_only=True), risk)
    side = "LONG" if exp.long >= exp.short else "SHORT"
    lvl = classify(exp.same_direction, settings.watch_same_direction, float("inf"),
                   previous.get("concentration"), margin=2)
    out["concentration"] = {
        "label": "Same direction before TP1", "value": exp.same_direction, "unit": "", "level": lvl,
        "watch": settings.watch_same_direction, "critical": None,
        "text": (f"{exp.same_direction} published signals are {side} and still before TP1. If every stop hit "
                 f"together, members would lose {exp.same_direction * risk:.1f}% at {risk:g}% each."),
    }
    return out


async def review_risk(s, settings: Settings, telegram, now=None) -> list[str]:
    """Update the stored levels; alert on a raised level and on the return to normal. Returns the
    keys that alerted."""
    state = await repo.get_state(s, STATE_KEY, {}) or {}
    previous = state.get("levels", {})
    current = await measures(s, settings, previous)
    alerted = []
    for key, m in current.items():
        before, after = previous.get(key), m["level"]
        if rank(after) > rank(before):
            level = "error" if after == "critical" else "warning"
            kind = f"risk.{key.split(':')[0]}"
            await repo.log_event(s, level, kind, m["text"], {"key": key, "value": m["value"], "level": after})
            if telegram:
                await telegram.enqueue_admin(s, fmt.alert(settings.app_name, level, kind, m["text"]))
            alerted.append(key)
        elif before and after is None:
            msg = f"{m['label']} back to normal: {m['value']}{m['unit']}"
            await repo.log_event(s, "info", "risk.normal", msg, {"key": key, "value": m["value"]})
            if telegram:
                await telegram.enqueue_admin(s, fmt.alert(settings.app_name, "info", "risk.normal", msg))
            alerted.append(key)
    await repo.set_state(s, STATE_KEY, {
        "at": (now or utcnow()).isoformat(), "levels": {k: m["level"] for k, m in current.items()},
        "measures": {k: {f: m[f] for f in ("label", "value", "unit", "level", "watch", "critical")}
                     for k, m in current.items()}})
    if alerted:
        log.warning("risk watch: %s", ", ".join(alerted))
    return alerted
