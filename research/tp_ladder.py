"""Multiple take-profits (TP1 / TP2 / TP3) on the validated 4H signals.

For every out-of-sample signal of A (RGP-4H), B (RSR-4H) and C (MLR-4H, walk-forward, ≤ 5 per
candle) this replays the price path on 1h candles (15m as a cross-check) and measures:

  1. distance from entry to the target and to the stop, in % of price, per coin;
  2. how often a target at k x ATR is reached before the original stop, within the time limit;
  3. the net result of TP1/TP2/TP3 scale-out plans, with the stop left alone, moved to
     break-even after TP1, or trailed (break-even after TP1, TP1 after TP2).

Conventions follow backtest/engine.py: market entry at the 4h open after the signal candle,
stop assumed first when it falls inside the same candle as a target, gaps fill at the open,
fees per fill (entry 0.07%, targets 0.02% maker, stops / time exits 0.08%). A moved stop takes
effect from the next candle, except that a candle which fills TP1 and closes back beyond the entry
must have crossed the break-even stop after the fill: the rest then exits at entry.

Usage:  python tp_ladder.py [--tf 1h|15m]
Output: results/tp_ladder_<tf>.md (+ .csv)
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
DATA = HERE / "data" / "parquet"
CAND = HERE / "results" / "candidates"
OUT = HERE / "results"
BAR4H = pd.Timedelta(hours=4)
COST_ENTRY, COST_TP, COST_EXIT = 0.0007, 0.0002, 0.0008

STRATS = {  # code: (trades file, SL in ATR, time limit in 4h candles)
    "RGP-4H": ("A_4h_regime_pullback_trades.csv", 4.0, 48),
    "RSR-4H": ("B_4h_regime_sweep_trades.csv", 3.0, 24),
    "MLR-4H": ("C_meta_4h_tp0.5_sl3.0_b24_thr_cal950_trades.csv", 3.0, 24),
}
LEVELS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]


@dataclass(frozen=True)
class Plan:
    name: str
    tps: tuple[float, ...]       # targets in ATR
    sizes: tuple[float, ...]     # fraction of the position closed at each target
    stop: str = "fixed"          # fixed | be (break-even after TP1) | trail (BE after TP1, TP1 after TP2)


PLANS = [
    Plan("Single TP 0.5 ATR (current)", (0.5,), (1.0,)),
    Plan("TP 0.5/1.0/1.5 · 50/30/20 · stop fixed", (0.5, 1.0, 1.5), (0.5, 0.3, 0.2)),
    Plan("TP 0.5/1.0/1.5 · 50/30/20 · BE after TP1", (0.5, 1.0, 1.5), (0.5, 0.3, 0.2), "be"),
    Plan("TP 0.5/1.0/1.5 · 50/30/20 · trailing", (0.5, 1.0, 1.5), (0.5, 0.3, 0.2), "trail"),
    Plan("TP 0.5/0.75/1.0 · 50/30/20 · BE after TP1", (0.5, 0.75, 1.0), (0.5, 0.3, 0.2), "be"),
    Plan("TP 0.5/1.0/1.5 · 34/33/33 · BE after TP1", (0.5, 1.0, 1.5), (0.34, 0.33, 0.33), "be"),
]


def load_signals() -> pd.DataFrame:
    rows = []
    for code, (fname, sl_atr, max_bars) in STRATS.items():
        t = pd.read_csv(CAND / fname, parse_dates=["entry_time"])
        if "period" in t:
            t = t[t.period == "out-of-sample"]
            atr = t.tp_dist / 0.5
        else:  # C: keep the best 5 per candle, as published (walk-forward probabilities)
            p = pd.read_parquet(HERE / "results" / "meta_preds_4h_tp0.5_sl3.0_b24.parquet",
                                columns=["ts", "symbol", "side", "prob"])
            p["entry_time"] = p.ts + BAR4H
            t = t.merge(p[["entry_time", "symbol", "side", "prob"]], on=["entry_time", "symbol", "side"], how="left")
            t = t.sort_values(["entry_time", "prob"], ascending=[True, False]).groupby("entry_time").head(5)
            atr = t.sl_pct / 100 * t.entry / sl_atr
        rows.append(pd.DataFrame({"strategy": code, "symbol": t.symbol.values, "side": t.side.values,
                                  "entry_time": t.entry_time.values, "entry": t.entry.values,
                                  "atr": atr.values, "sl_atr": sl_atr, "max_bars": max_bars}))
    s = pd.concat(rows, ignore_index=True)
    s["entry_time"] = pd.to_datetime(s.entry_time, utc=True)
    return s


MINUTES = {"1h": 60, "15m": 15}


def load_paths(tf: str, symbols) -> dict[str, tuple[np.ndarray, ...]]:
    out = {}
    for sym in symbols:
        d = pd.read_parquet(DATA / f"{sym}_{tf}.parquet", columns=["ts", "open", "high", "low", "close"])
        ts = d.ts.dt.tz_convert(None).to_numpy().astype("datetime64[ns]")
        out[sym] = (ts, d.open.to_numpy(), d.high.to_numpy(), d.low.to_numpy(), d.close.to_numpy())
    return out


def path_for(sig, paths, tf: str):
    ts, o, h, lo, c = paths[sig.symbol]
    start = np.datetime64(sig.entry_time.tz_convert(None).to_datetime64(), "ns")
    bars = int(sig.max_bars) * 240 // MINUTES[tf]
    i = int(np.searchsorted(ts, start))
    j = i + bars
    if j > len(ts) or ts[i] != start or ts[j - 1] - ts[i] != np.timedelta64((bars - 1) * MINUTES[tf], "m"):
        return None  # incomplete path: data gap, outside the data range, or the signal is too recent
    return o[i:j], h[i:j], lo[i:j], c[i:j]


def first_hits(side, entry, atr, sl_atr, path):
    """Index of the first candle touching the stop and each target level (len(path) if never)."""
    o, h, lo, _ = path
    n = len(o)
    stop = entry - side * sl_atr * atr
    stop_hit = (lo <= stop) if side == 1 else (h >= stop)
    s = int(np.argmax(stop_hit)) if stop_hit.any() else n
    res = {}
    for k in LEVELS:
        lv = entry + side * k * atr
        hit = (h >= lv) if side == 1 else (lo <= lv)
        res[k] = int(np.argmax(hit)) if hit.any() else n
    return s, res


def run_plan(plan: Plan, side, entry, atr, sl_atr, path):
    o, h, lo, c = path
    stop = entry - side * sl_atr * atr
    risk = sl_atr * atr / entry
    levels = [entry + side * k * atr for k in plan.tps]
    remaining, filled, pnl = 1.0, 0, -COST_ENTRY
    exit_kind, exit_i = "TIME", len(o) - 1
    for i in range(len(o)):
        adverse = lo[i] <= stop if side == 1 else h[i] >= stop
        if adverse:  # stop first, at the level in force when the candle opened
            gap = i > 0 and (o[i] <= stop if side == 1 else o[i] >= stop)
            px = o[i] if gap else stop
            pnl += remaining * (side * (px / entry - 1) - COST_EXIT)
            remaining = 0.0
            exit_kind, exit_i = ("SL" if filled == 0 else "STOP_AFTER_TP"), i
            break
        new_stop, filled_at_open = stop, filled
        while filled < len(levels):
            lv = levels[filled]
            if not (h[i] >= lv if side == 1 else lo[i] <= lv):
                break
            gap = i > 0 and (o[i] >= lv if side == 1 else o[i] <= lv)
            px = o[i] if gap else lv
            pnl += plan.sizes[filled] * (side * (px / entry - 1) - COST_TP)
            remaining -= plan.sizes[filled]
            filled += 1
            if plan.stop in ("be", "trail") and filled == 1:
                new_stop = entry
            if plan.stop == "trail" and filled >= 2:
                new_stop = levels[filled - 2]
        if remaining <= 1e-9:
            exit_kind, exit_i = "ALL_TP", i
            break
        if filled_at_open == 0 and filled and plan.stop in ("be", "trail") and (c[i] <= entry if side == 1 else c[i] >= entry):
            pnl += remaining * -COST_EXIT  # TP1 filled, then back through the entry in this candle
            remaining = 0.0
            exit_kind, exit_i = "STOP_AFTER_TP", i
            break
        stop = new_stop
    else:
        pnl += remaining * (side * (c[-1] / entry - 1) - COST_EXIT)
    return pnl, pnl / risk, filled, exit_kind, exit_i


def equity(g: pd.DataFrame, risk: float = 0.005) -> tuple[float, float]:
    g = g.sort_values("exit_time")
    eq = np.cumprod(1 + g.r.to_numpy() * risk)
    dd = 1 - eq / np.maximum.accumulate(eq)
    years = (g.exit_time.iloc[-1] - g.exit_time.iloc[0]).days / 365.25
    return float(eq[-1] ** (1 / years) - 1), float(dd.max())


def pf(x):
    neg = -x[x < 0].sum()
    return float(x[x > 0].sum() / neg) if neg > 0 else float("inf")


def main(tf: str) -> None:
    sigs = load_signals()
    paths = load_paths(tf, sorted(sigs.symbol.unique()))
    keep = []
    for sig in sigs.itertuples():
        p = path_for(sig, paths, tf)
        if p is not None:
            keep.append((sig, p))
    print(f"{len(keep)} of {len(sigs)} signals have a complete {tf} path")

    # 1) distances, 2) hit rates by target level
    dist, hits = [], []
    for sig, p in keep:
        s, first = first_hits(sig.side, sig.entry, sig.atr, sig.sl_atr, p)
        bar_h = MINUTES[tf] / 60
        dist.append({"strategy": sig.strategy, "symbol": sig.symbol,
                     "tp_pct": 0.5 * sig.atr / sig.entry * 100, "sl_pct": sig.sl_atr * sig.atr / sig.entry * 100,
                     "hours_to_tp1": (first[0.5] + 1) * bar_h if first[0.5] < s else np.nan})
        hits.append({"strategy": sig.strategy, **{k: first[k] < s for k in LEVELS}})
    dist, hits = pd.DataFrame(dist), pd.DataFrame(hits)

    # 3) scale-out plans
    res = []
    for plan in PLANS:
        for sig, p in keep:
            net, r, filled, kind, exit_i = run_plan(plan, sig.side, sig.entry, sig.atr, sig.sl_atr, p)
            res.append({"plan": plan.name, "strategy": sig.strategy, "net": net, "r": r, "filled": filled,
                        "kind": kind, "year": sig.entry_time.year, "symbol": sig.symbol,
                        "entry_time": sig.entry_time,
                        "exit_time": sig.entry_time + pd.Timedelta(minutes=(exit_i + 1) * MINUTES[tf])})
    res = pd.DataFrame(res)
    # the book publishes one signal per coin per candle: RGP > RSR > MLR (as the live engine)
    prio = res.strategy.map({"RGP-4H": 0, "RSR-4H": 1, "MLR-4H": 2})
    in_book = ~res.assign(p=prio).sort_values("p").duplicated(["plan", "entry_time", "symbol"]).sort_index()

    lines = [f"# TP1 / TP2 / TP3 study on the validated 4H signals ({tf} paths)", "",
             f"{len(keep)} out-of-sample signals, 2022 → Oct 2026. Generated by `research/tp_ladder.py --tf {tf}`.", ""]

    lines += ["## 1. Distance from entry to target and stop (% of price)", "",
              "| Coin | Signals | Target (TP 0.5 ATR) median | 25–75% range | Stop median | Median time to target |",
              "|---|---|---|---|---|---|"]
    for sym, g in list(dist.groupby("symbol")) + [("All coins", dist)]:
        q = g.tp_pct.quantile([0.25, 0.5, 0.75])
        lines.append(f"| {sym.replace('USDT', '')} | {len(g)} | {q[0.5]:.2f}% | {q[0.25]:.2f}–{q[0.75]:.2f}% | "
                     f"{g.sl_pct.median():.2f}% | {g.hours_to_tp1.median():.0f} h |")
    lines += ["", "| Strategy | Target median | Stop median | Reward : risk |", "|---|---|---|---|"]
    for code, g in dist.groupby("strategy"):
        lines.append(f"| {code} | {g.tp_pct.median():.2f}% | {g.sl_pct.median():.2f}% | "
                     f"1 : {g.sl_pct.median() / g.tp_pct.median():.0f} |")

    lines += ["", "## 2. How often a target is reached before the stop", "",
              "| Strategy | " + " | ".join(f"{k} ATR" for k in LEVELS) + " |", "|---|" + "---|" * len(LEVELS)]
    for code, g in list(hits.groupby("strategy")) + [("All", hits)]:
        lines.append(f"| {code} | " + " | ".join(f"{g[k].mean() * 100:.1f}%" for k in LEVELS) + " |")

    lines += ["", "## 3. Scale-out plans (net of costs)", "",
              "Win = the signal's total result is positive. Net = average result per signal, % of position.", "",
              "| Strategy | Plan | Win rate | TP1 | TP2 | TP3 | Net/signal | Profit factor | Avg R | Worst year net |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    table = []
    for (code, name), g in res.groupby(["strategy", "plan"], sort=False):
        by_year = g.groupby("year").net.mean()
        row = {"strategy": code, "plan": name, "signals": len(g), "win_rate": (g.net > 0).mean(),
               "tp1": (g.filled >= 1).mean(), "tp2": (g.filled >= 2).mean(), "tp3": (g.filled >= 3).mean(),
               "net_pct": g.net.mean() * 100, "pf": pf(g.net.to_numpy()), "avg_r": g.r.mean(),
               "worst_year_net_pct": by_year.min() * 100}
        table.append(row)
        single = name.startswith("Single")
        tp2 = "—" if single else f"{row['tp2'] * 100:.1f}%"
        tp3 = "—" if single else f"{row['tp3'] * 100:.1f}%"
        lines.append(f"| {code} | {name} | {row['win_rate'] * 100:.1f}% | {row['tp1'] * 100:.1f}% | {tp2} | {tp3} | "
                     f"{row['net_pct']:+.3f}% | {row['pf']:.2f} | {row['avg_r']:+.3f} | {row['worst_year_net_pct']:+.2f}% |")
    book = res[in_book].groupby("plan", sort=False)
    lines += ["", ("**Book (A + B + C)** · CAGR and max drawdown when every signal risks 0.5% of equity "
                   "(compounded in exit order)"), "",
              "| Plan | Signals | Win rate | TP1 | TP2 | TP3 | Net/signal | Profit factor | Avg R | CAGR | Max drawdown |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, g in book:
        cagr, mdd = equity(g)
        hit = [f"{(g.filled >= n).mean() * 100:.1f}%" for n in (1, 2, 3)]
        lines.append(f"| {name} | {len(g)} | {(g.net > 0).mean() * 100:.1f}% | {' | '.join(hit)} | "
                     f"{g.net.mean() * 100:+.3f}% | {pf(g.net.to_numpy()):.2f} | {g.r.mean():+.3f} | "
                     f"{cagr * 100:+.1f}% | {mdd * 100:.1f}% |")
        table.append({"strategy": "BOOK", "plan": name, "signals": len(g), "win_rate": (g.net > 0).mean(),
                      "net_pct": g.net.mean() * 100, "pf": pf(g.net.to_numpy()), "avg_r": g.r.mean(),
                      "cagr": cagr, "max_dd": mdd})

    lines += ["", "## 4. Benchmark figures per strategy (for the website)", "",
              "| Strategy | Plan | Signals | Win rate | Break-even win rate | Avg win | Avg loss | Net/signal | PF |",
              "|---|---|---|---|---|---|---|---|---|"]
    for (code, name), g in list(res.groupby(["strategy", "plan"], sort=False)) + \
            [(("BOOK", n), g) for n, g in book]:
        if not (name.startswith("Single") or name == PLANS[2].name):
            continue
        w, lo = g.net[g.net > 0], -g.net[g.net <= 0]
        be = lo.mean() / (w.mean() + lo.mean())
        lines.append(f"| {code} | {name} | {len(g)} | {(g.net > 0).mean() * 100:.1f}% | {be * 100:.1f}% | "
                     f"+{w.mean() * 100:.2f}% | −{lo.mean() * 100:.2f}% | {g.net.mean() * 100:+.3f}% | "
                     f"{pf(g.net.to_numpy()):.2f} |")

    (OUT / f"tp_ladder_{tf}.md").write_text("\n".join(lines) + "\n")
    pd.DataFrame(table).to_csv(OUT / f"tp_ladder_{tf}.csv", index=False)
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h", choices=["1h", "15m"])
    main(ap.parse_args().tf)
