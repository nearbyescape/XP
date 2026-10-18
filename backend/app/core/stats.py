"""Performance statistics over closed signals.

Input rows are mappings with: exit_at (datetime), pnl_net (fraction of notional), r_multiple,
exit_reason. Definitions match the research report: win = net P&L > 0; profit factor = sum of
net wins / |sum of net losses|; break-even win rate = avg loss / (avg win + avg loss).
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable, Mapping
from datetime import datetime


def kpis(rows: Iterable[Mapping], days: float | None = None) -> dict:
    rows = sorted(rows, key=lambda r: r["exit_at"])
    n = len(rows)
    if n == 0:
        return {"signals": 0, "wins": 0, "losses": 0, "win_rate": None, "breakeven_win_rate": None,
                "avg_win": None, "avg_loss": None, "profit_factor": None, "expectancy": None,
                "avg_r": None, "total_r": 0.0, "max_consecutive_losses": 0,
                "signals_per_day": 0.0 if days else None, "by_reason": {}}
    nets = [float(r["pnl_net"]) for r in rows]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    avg_w = sum(wins) / len(wins) if wins else 0.0
    avg_l = -sum(losses) / len(losses) if losses else 0.0
    gross_loss = -sum(losses)
    streak = cur = 0
    for x in nets:
        cur = cur + 1 if x <= 0 else 0
        streak = max(streak, cur)
    rs = [float(r["r_multiple"] or 0.0) for r in rows]
    reasons: dict[str, int] = {}
    for r in rows:
        reasons[r["exit_reason"]] = reasons.get(r["exit_reason"], 0) + 1
    return {
        "signals": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / n,
        "breakeven_win_rate": avg_l / (avg_w + avg_l) if (avg_w + avg_l) > 0 else None,
        "avg_win": avg_w if wins else None,
        "avg_loss": avg_l if losses else None,
        "profit_factor": (sum(wins) / gross_loss) if gross_loss > 0 else None,
        "expectancy": sum(nets) / n,
        "avg_r": sum(rs) / n,
        "total_r": sum(rs),
        "max_consecutive_losses": streak,
        "signals_per_day": (n / days) if days else None,
        "by_reason": reasons,
    }


def equity_curve(rows: Iterable[Mapping], risk: float = 0.005) -> dict:
    """Account curve when every signal risks `risk` of equity (compounded, in exit order)."""
    rows = sorted(rows, key=lambda r: r["exit_at"])
    eq, peak, max_dd = 1.0, 1.0, 0.0
    points = []
    for r in rows:
        eq *= 1 + float(r["r_multiple"] or 0.0) * risk
        peak = max(peak, eq)
        dd = 1 - eq / peak
        max_dd = max(max_dd, dd)
        points.append({"t": r["exit_at"], "equity": eq, "drawdown": dd})
    return {"risk": risk, "points": points, "total_return": eq - 1, "max_drawdown": max_dd}


def monthly(rows: Iterable[Mapping]) -> list[dict]:
    buckets: OrderedDict[str, list] = OrderedDict()
    for r in sorted(rows, key=lambda r: r["exit_at"]):
        t: datetime = r["exit_at"]
        buckets.setdefault(f"{t:%Y-%m}", []).append(r)
    out = []
    for month, rs in buckets.items():
        k = kpis(rs)
        out.append({"month": month, "signals": k["signals"], "win_rate": k["win_rate"],
                    "profit_factor": k["profit_factor"], "total_r": k["total_r"],
                    "expectancy": k["expectancy"]})
    return out


def rolling_health(last_rows: Iterable[Mapping]) -> dict:
    k = kpis(last_rows)
    return {"signals": k["signals"], "win_rate": k["win_rate"], "profit_factor": k["profit_factor"]}
