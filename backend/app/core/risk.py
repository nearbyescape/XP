"""Risk guard: open risk across published signals and the early-warning levels for administrators.

Nothing here changes which signals publish or how they are recorded. Open risk counts published
signals still before TP1: until TP1 fills their stop is the original one; after it the rest of the
position runs with the stop at entry and can no longer lose.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

LEVELS = (None, "watch", "critical")


def at_risk(sig) -> bool:
    """An open signal whose stop can still lose money (before TP1, or without the stop-to-entry rule)."""
    return sig.status == "ACTIVE" and (not (sig.targets_hit or 0) or not sig.breakeven)


@dataclass(frozen=True)
class Exposure:
    open: int        # published signals still open
    at_risk: int     # of which still before TP1
    long: int        # at risk, by direction
    short: int
    risk_pct: float  # risk per signal, % of the account

    @property
    def open_risk_pct(self) -> float:
        """Account loss if every signal before TP1 hit its stop together, at `risk_pct` each."""
        return self.at_risk * self.risk_pct

    @property
    def same_direction(self) -> int:
        return max(self.long, self.short)

    def as_dict(self) -> dict:
        return {"open": self.open, "at_risk": self.at_risk, "long": self.long, "short": self.short,
                "risk_pct": self.risk_pct, "open_risk_pct": self.open_risk_pct}


def exposure(rows: Iterable, risk_pct: float) -> Exposure:
    rows = [r for r in rows if r.status == "ACTIVE"]
    risky = [r for r in rows if at_risk(r)]
    longs = sum(1 for r in risky if r.side == 1)
    return Exposure(len(rows), len(risky), longs, len(risky) - longs, risk_pct)


def classify(value: float | None, watch: float, critical: float, previous: str | None,
             margin: float, higher_is_worse: bool = True) -> str | None:
    """Level of a measure. Once raised, a level holds until the value is `margin` back inside the
    watch threshold, so a value hovering at the threshold does not alert again and again."""
    if value is None:
        return None
    v, w, c = (value, watch, critical) if higher_is_worse else (-value, -watch, -critical)
    if v >= c:
        return "critical"
    if v >= w or (previous and v >= w - margin):
        return "watch"
    return None


def rank(level: str | None) -> int:
    return LEVELS.index(level)
