"""Bar-by-bar trade simulator (single pass state machine per symbol).

Execution model (deliberately conservative):
* A signal is evaluated on a CLOSED bar i. Two entry modes:
    - market: filled at the OPEN of bar i+1 (taker).
    - limit : a resting order at `limit_px[i]` that is live for bars i+1 .. i+valid. A newer
              signal replaces the pending order (the bot re-quotes every bar). Fills at the level,
              or at the open if the bar gaps through it.
* Stop-loss / take-profit are resting orders checked against each bar's high/low.
  If both are touched inside the same bar we assume the STOP filled first.
* A limit order only counts as filled if price trades through it by `fill_pen` (default 0.05%);
  touch-and-reverse fills (the easy winners) are therefore excluded.
* On the bar a LIMIT entry fills we don't know the path, so: stop if low<=SL (long),
  take-profit only if the bar CLOSES beyond TP (proof the move happened after the fill).
* If a bar opens beyond a level (gap), the fill is the bar's open, not the level.
* Optional TP1 scale-out: `tp1_frac` closes at TP1, then the stop moves to entry (break-even).
  If TP1 and break-even are touched in the same bar we assume the remainder was stopped at BE.
* Optional dynamic exit (e.g. "close > SMA5") fills at that bar's close. Time stop closes at
  the close of the `max_bars`-th bar in the trade.
* Costs (fraction of notional, fee + slippage): `cost_entry` on entry, `cost_tp` on take-profit
  fills (resting limit = maker), `cost_exit` on stops / time / dynamic exits (taker + slippage).
* One position per symbol; while a position is open new signals are ignored.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numba import njit

REASONS = np.array(["tp", "sl", "be", "dyn", "time", "eod"])


@njit(cache=True)
def _simulate(o, h, l, c, side, limit_px, valid, tp_d, sl_d, tp1_d, tp1_frac, max_bars,
              dyn_long, dyn_short, cost_entry, cost_tp, cost_exit, fill_pen):
    n = o.shape[0]
    cap = n // 2 + 1
    entry_idx = np.empty(cap, np.int64)
    exit_idx = np.empty(cap, np.int64)
    sides = np.empty(cap, np.int8)
    entry_px = np.empty(cap, np.float64)
    exit_px = np.empty(cap, np.float64)
    pnl = np.empty(cap, np.float64)
    reason = np.empty(cap, np.int8)
    tp1_flag = np.empty(cap, np.bool_)
    use_tp1 = tp1_frac > 0.0
    k = 0

    in_pos = False
    p_side = 0          # pending order side
    p_bar = -1          # bar that created the pending order
    s = 0
    e = 0
    ep = tp = sl = t1 = 0.0
    remaining = realized = 0.0
    tp1_hit = False

    for j in range(n):
        just_filled = False
        # ---- try to fill a pending order on bar j ---------------------------------------
        if not in_pos and p_side != 0:
            if j - p_bar > valid:
                p_side = 0
            else:
                lim = limit_px[p_bar]
                filled = False
                if not np.isfinite(lim):            # market order -> next open
                    fill = o[j]
                    filled = True
                elif p_side == 1 and l[j] <= lim * (1.0 - fill_pen):
                    fill = min(o[j], lim)
                    filled = True
                    just_filled = True
                elif p_side == -1 and h[j] >= lim * (1.0 + fill_pen):
                    fill = max(o[j], lim)
                    filled = True
                    just_filled = True
                if filled:
                    s = p_side
                    ep = fill
                    e = j
                    if s == 1:
                        tp = ep + tp_d[p_bar]
                        sl = ep - sl_d[p_bar]
                        t1 = ep + tp1_d[p_bar]
                    else:
                        tp = ep - tp_d[p_bar]
                        sl = ep + sl_d[p_bar]
                        t1 = ep - tp1_d[p_bar]
                    remaining = 1.0
                    realized = -cost_entry
                    tp1_hit = False
                    in_pos = True
                    p_side = 0
        # ---- manage an open position on bar j -------------------------------------------
        if in_pos:
            px = np.nan
            why = -1
            if s == 1:
                if j > e and o[j] <= sl:
                    px = o[j]
                    why = 2 if tp1_hit else 1
                elif j > e and o[j] >= tp:
                    px = o[j]
                    why = 0
                elif l[j] <= sl:
                    px = sl
                    why = 2 if tp1_hit else 1
                elif just_filled:
                    if c[j] >= tp:
                        px = tp
                        why = 0
                elif use_tp1 and not tp1_hit and h[j] >= t1:
                    realized += tp1_frac * (t1 / ep - 1.0 - cost_tp)
                    remaining -= tp1_frac
                    tp1_hit = True
                    sl = ep
                    if l[j] <= sl:
                        px = sl
                        why = 2
                    elif h[j] >= tp:
                        px = tp
                        why = 0
                elif h[j] >= tp:
                    px = tp
                    why = 0
            else:
                if j > e and o[j] >= sl:
                    px = o[j]
                    why = 2 if tp1_hit else 1
                elif j > e and o[j] <= tp:
                    px = o[j]
                    why = 0
                elif h[j] >= sl:
                    px = sl
                    why = 2 if tp1_hit else 1
                elif just_filled:
                    if c[j] <= tp:
                        px = tp
                        why = 0
                elif use_tp1 and not tp1_hit and l[j] <= t1:
                    realized += tp1_frac * (1.0 - t1 / ep - cost_tp)
                    remaining -= tp1_frac
                    tp1_hit = True
                    sl = ep
                    if h[j] >= sl:
                        px = sl
                        why = 2
                    elif l[j] <= tp:
                        px = tp
                        why = 0
                elif l[j] <= tp:
                    px = tp
                    why = 0
            if why < 0:
                if (s == 1 and dyn_long[j]) or (s == -1 and dyn_short[j]):
                    px = c[j]
                    why = 3
                elif j - e + 1 >= max_bars:
                    px = c[j]
                    why = 4
                elif j == n - 1:
                    px = c[j]
                    why = 5
            if why >= 0:
                exit_cost = cost_tp if why == 0 else cost_exit
                if s == 1:
                    ret = realized + remaining * (px / ep - 1.0 - exit_cost)
                else:
                    ret = realized + remaining * (1.0 - px / ep - exit_cost)
                entry_idx[k] = e
                exit_idx[k] = j
                sides[k] = s
                entry_px[k] = ep
                exit_px[k] = px
                pnl[k] = ret
                reason[k] = why
                tp1_flag[k] = tp1_hit
                k += 1
                in_pos = False
        # ---- bar j closed: a signal (re)places the pending order -----------------------
        if not in_pos and side[j] != 0 and np.isfinite(sl_d[j]) and sl_d[j] > 0:
            p_side = side[j]
            p_bar = j
    return (entry_idx[:k], exit_idx[:k], sides[:k], entry_px[:k], exit_px[:k],
            pnl[:k], reason[:k], tp1_flag[:k])


def simulate(df: pd.DataFrame, sig: dict, *, cost_side: float = 0.0007, max_bars: int = 24,
             tp1_frac: float = 0.0, symbol: str = "", cost_entry: float | None = None,
             cost_tp: float | None = None, cost_exit: float | None = None,
             valid: int = 1, fill_pen: float = 0.0005) -> pd.DataFrame:
    """Run one symbol. `sig` keys: side (int8, +1/-1/0), tp_d, sl_d (price distances),
    optional tp1_d, dyn_long, dyn_short, limit_px (absolute limit price; NaN/absent = market).
    Any cost not given defaults to `cost_side`. `fill_pen`: a limit order only counts as filled
    if price trades THROUGH it by this fraction (queue-position / adverse-selection haircut)."""
    n = len(df)
    ce = cost_side if cost_entry is None else cost_entry
    ct = cost_side if cost_tp is None else cost_tp
    cx = cost_side if cost_exit is None else cost_exit
    out = _simulate(
        df["open"].to_numpy(np.float64), df["high"].to_numpy(np.float64),
        df["low"].to_numpy(np.float64), df["close"].to_numpy(np.float64),
        np.asarray(sig["side"], np.int8),
        np.asarray(sig.get("limit_px", np.full(n, np.nan)), np.float64), int(valid),
        np.asarray(sig["tp_d"], np.float64), np.asarray(sig["sl_d"], np.float64),
        np.asarray(sig.get("tp1_d", np.full(n, np.inf)), np.float64),
        float(tp1_frac), int(max_bars),
        np.asarray(sig.get("dyn_long", np.zeros(n, np.bool_)), np.bool_),
        np.asarray(sig.get("dyn_short", np.zeros(n, np.bool_)), np.bool_),
        float(ce), float(ct), float(cx), float(fill_pen),
    )
    e, x, s, ep, xp, r, why, t1 = out
    ts = df["ts"].to_numpy()
    return pd.DataFrame({
        "symbol": symbol, "entry_time": ts[e], "exit_time": ts[x], "side": s,
        "entry": ep, "exit": xp, "pnl": r, "bars": x - e + 1, "reason": REASONS[why], "tp1_hit": t1,
    })


def metrics(trades: pd.DataFrame, days: float, size: float = 0.10) -> dict:
    """Summary stats. `size` = fraction of account allocated per signal (non-compounding),
    used for the account-level return / drawdown figures."""
    n = len(trades)
    if n == 0:
        return {"trades": 0}
    order = np.argsort(trades["exit_time"].to_numpy(), kind="stable")
    r = trades["pnl"].to_numpy()[order]
    wins = r[r > 0]
    losses = r[r <= 0]
    gross_loss = -losses.sum()
    eq = np.concatenate([[0.0], np.cumsum(r * size)])
    dd = (np.maximum.accumulate(eq) - eq).max()
    streak = cur = 0
    for v in r:
        cur = cur + 1 if v <= 0 else 0
        streak = max(streak, cur)
    avg_w = wins.mean() if len(wins) else 0.0
    avg_l = -losses.mean() if len(losses) else 0.0
    return {
        "trades": n,
        "signals_per_day": n / days,
        "win_rate": len(wins) / n,
        "breakeven_wr": avg_l / (avg_w + avg_l) if (avg_w + avg_l) > 0 else np.nan,
        "avg_win_pct": avg_w * 100,
        "avg_loss_pct": avg_l * 100,
        "expectancy_pct": r.mean() * 100,
        "profit_factor": wins.sum() / gross_loss if gross_loss > 0 else np.inf,
        "worst_trade_pct": r.min() * 100,
        "max_consec_losses": streak,
        "acct_return_pct": eq[-1] * 100,
        "acct_max_dd_pct": dd * 100,
        "avg_bars": trades["bars"].mean(),
    }
