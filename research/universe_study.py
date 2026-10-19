"""Universe-expansion study (Oct 2026): today's book (C on 10 coins) vs C retrained on 20 coins.

    python research/data/fetch_klines.py --source binance --market spot --intervals 4h --start 2017-07 \
        --symbols ZECUSDT,NEARUSDT,BCHUSDT,FILUSDT,AAVEUSDT,UNIUSDT,LTCUSDT,XLMUSDT,TRXUSDT,DASHUSDT
    (same with --intervals 1h --start 2022-01)
    python research/meta_label.py --tf 4h --tp 0.5 --sl 3.0 --bars 24 --oos 2022-01-01 --universe 20
    python research/universe_study.py            # its output is kept in results/universe20.md

The 10 new coins were fixed by rule before any result (see NEW10 in meta_label.py), and so were the pass
criteria at the end of this file.

Same construction as the earlier studies: A/B out-of-sample trades on the original 10 coins, C from the
walk-forward predictions (threshold thr_cal950, one position per coin, best 5 per candle), duplicates on
the same coin and candle resolved A > B > C, every signal replayed on 1h candles with the live lifecycle
(TP 0.5/1.0/1.5 ATR closing 50/30/20 %, stop to entry after TP1, time stop), live costs. Published =
4H candle closing inside 09:00-23:00 IST.
"""
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "backend"))
import tp_ladder as L  # noqa: E402
from meta_label import NEW10, SYMBOLS as OLD10  # noqa: E402
from app.core.lifecycle import Bar, Costs, TradeState, pnl, step, target_prices  # noqa: E402

RES = L.HERE / "results"
IST = pd.Timedelta(hours=5, minutes=30)
RISK = 0.005
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")


def signals(c_trades: str, c_preds: str) -> pd.DataFrame:
    rows = []
    for code, (fname, sl_atr, max_bars) in L.STRATS.items():
        if code == "MLR-4H":
            t = pd.read_csv(L.CAND / c_trades, parse_dates=["entry_time"])
            p = pd.read_parquet(RES / c_preds, columns=["ts", "symbol", "side", "prob"])
            p["entry_time"] = p.ts + L.BAR4H
            t = t.merge(p[["entry_time", "symbol", "side", "prob"]], on=["entry_time", "symbol", "side"], how="left")
            t = t.sort_values(["entry_time", "prob"], ascending=[True, False]).groupby("entry_time").head(5)
            atr = t.sl_pct / 100 * t.entry / sl_atr
        else:
            t = pd.read_csv(L.CAND / fname, parse_dates=["entry_time"])
            t = t[t.period == "out-of-sample"]
            atr = t.tp_dist / 0.5
        rows.append(pd.DataFrame({"strategy": code, "symbol": t.symbol.values, "side": t.side.values,
                                  "entry_time": t.entry_time.values, "entry": t.entry.values,
                                  "atr": atr.values, "sl_atr": sl_atr, "max_bars": max_bars}))
    s = pd.concat(rows, ignore_index=True)
    s["entry_time"] = pd.to_datetime(s.entry_time, utc=True)
    prio = s.strategy.map({"RGP-4H": 0, "RSR-4H": 1, "MLR-4H": 2})
    return s[~s.assign(p=prio).sort_values("p").duplicated(["entry_time", "symbol"]).sort_index()]


def replay(sigs: pd.DataFrame, paths) -> pd.DataFrame:
    rows = []
    for sig in sigs.itertuples():
        p = L.path_for(sig, paths, "1h")
        if p is None:
            continue
        o, h, lo, c = p
        t0 = sig.entry_time.to_pydatetime()
        targets = target_prices(sig.side, sig.entry, sig.atr, (0.5, 1.0, 1.5))
        stop0 = sig.entry - sig.side * sig.sl_atr * sig.atr
        st = TradeState(sig.side, sig.entry, targets[0], stop0, t0, t0 + timedelta(hours=4 * int(sig.max_bars)),
                        targets=targets, sizes=(0.5, 0.3, 0.2), breakeven=True)
        for i in range(len(o)):
            if step(st, Bar(t0 + timedelta(hours=i), t0 + timedelta(hours=i + 1), o[i], h[i], lo[i], c[i])):
                break
        r = pnl(st, Costs())
        ist = sig.entry_time + IST
        rows.append({"entry": sig.entry_time, "exit": pd.Timestamp(st.exit_at), "symbol": sig.symbol,
                     "side": sig.side, "strategy": sig.strategy, "net": r["net"], "r": r["r"],
                     "risk_end": pd.Timestamp(st.fills[0][0]) if st.targets_hit else pd.Timestamp(st.exit_at),
                     "session": 9 * 60 <= ist.hour * 60 + ist.minute < 23 * 60})
    return pd.DataFrame(rows)


def k(d: pd.DataFrame, days: float) -> dict:
    if d.empty:
        return {"n": 0}
    w, lo = d.net[d.net > 0].sum(), -d.net[d.net <= 0].sum()
    r = d.sort_values("exit").r.to_numpy()
    eq = np.cumprod(1 + r * RISK)
    losses = (d.sort_values("exit").net <= 0).astype(int).to_numpy()
    streak = max((len(x) for x in "".join(map(str, losses)).split("0")), default=0)
    return {"n": len(d), "day": len(d) / days, "wr": (d.net > 0).mean(), "pf": w / lo if lo else np.inf,
            "growth": eq[-1] - 1, "dd": float((1 - eq / np.maximum.accumulate(eq)).max()), "streak": streak}


def line(name, x):
    if not x["n"]:
        return f"  {name:<34} no signals"
    return (f"  {name:<34} {x['n']:>5} ({x['day']:.2f}/day) · win {x['wr'] * 100:5.1f}% · PF {x['pf']:.2f} · "
            f"growth {x['growth'] * 100:+6.1f}% · max drop {x['dd'] * 100:4.1f}% · losses in a row {x['streak']}")


def concentration(d: pd.DataFrame):
    grid = pd.date_range(d.entry.min().floor("4h"), d.exit.max(), freq="4h").to_numpy()
    ent, end, side = d.entry.to_numpy(), d.risk_end.to_numpy(), d.side.to_numpy()
    same, opened = [], []
    for g in grid:
        live = (ent <= g) & (end > g)
        opened.append(live.sum())
        same.append(max((live & (side == 1)).sum(), (live & (side == -1)).sum()))
    same, opened = np.array(same), np.array(opened)
    return {"open_max": int(opened.max()), "open_p99": float(np.percentile(opened, 99)),
            "open_ge10": float((opened >= 10).mean()), "same_max": int(same.max()),
            "same_p99": float(np.percentile(same, 99)), "same_ge12_days": int(len({pd.Timestamp(g).date() for g, x in zip(grid, same) if x >= 12}))}


if __name__ == "__main__":
    paths = L.load_paths("1h", OLD10 + NEW10)
    books = {
        "today (C on 10)": replay(signals("C_meta_4h_tp0.5_sl3.0_b24_thr_cal950_trades.csv",
                                          "meta_preds_4h_tp0.5_sl3.0_b24.parquet"), paths),
        "new (C on 20)": replay(signals("C_meta_4h_tp0.5_sl3.0_b24_u20_thr_cal950_trades.csv",
                                        "meta_preds_4h_tp0.5_sl3.0_b24_u20.parquet"), paths),
    }
    end = min(b.entry.max() for b in books.values())
    start = pd.Timestamp("2022-01-01", tz="UTC")
    periods = {"2022-01 → now": (start, end), "2022–2024": (start, SPLIT), "2025 → now": (SPLIT, end)}
    out = {}
    for pname, (a, b) in periods.items():
        days = (b - a).days
        print(f"\n=== {pname} ({days} days), published signals ===")
        for bname, t in books.items():
            p = t[(t.entry >= a) & (t.entry < b) & t.session]
            groups = {"all strategies": p, "A+B": p[p.strategy != "MLR-4H"],
                      "C on the original 10": p[(p.strategy == "MLR-4H") & p.symbol.isin(OLD10)]}
            if bname.startswith("new"):
                groups["C on the new 10"] = p[(p.strategy == "MLR-4H") & p.symbol.isin(NEW10)]
            print(f" {bname}")
            for g, d in groups.items():
                out[(pname, bname, g)] = k(d, days)
                print(line(g, out[(pname, bname, g)]))

    ALL = "2022-01 → now"
    print("\n=== new coins, C only, published, 2022-01 → now (information only: coins are not picked by result) ===")
    t = books["new (C on 20)"]
    p = t[(t.entry >= start) & t.session & (t.strategy == "MLR-4H")]
    for s in NEW10:
        print(line(s, k(p[p.symbol == s], (end - start).days)))

    print("\n=== open signals before TP1 (published), 2022-01 → now ===")
    for bname, t in books.items():
        c = concentration(t[(t.entry >= start) & t.session])
        print(f"  {bname:<18} most at once {c['open_max']} (99th pct {c['open_p99']:.0f}; 10 or more "
              f"{c['open_ge10'] * 100:.1f}% of 4H checks) · same direction max {c['same_max']} "
              f"(99th pct {c['same_p99']:.0f}; 12 or more on {c['same_ge12_days']} days)")

    n1, n2 = out[(ALL, "new (C on 20)", "C on the new 10")], out[("2025 → now", "new (C on 20)", "C on the new 10")]
    o_old, o_new = out[(ALL, "today (C on 10)", "C on the original 10")], out[(ALL, "new (C on 20)", "C on the original 10")]
    b_old, b_new = out[(ALL, "today (C on 10)", "all strategies")], out[(ALL, "new (C on 20)", "all strategies")]
    checks = [
        (f"1. new 10 coins: win {n1['wr'] * 100:.1f}% >= 85%, PF {n1['pf']:.2f} >= 1.3, 2025+ PF {n2['pf']:.2f} >= 1.2",
         n1["wr"] >= 0.85 and n1["pf"] >= 1.3 and n2["pf"] >= 1.2),
        (f"2. original 10 coins: C PF {o_new['pf']:.2f} vs today {o_old['pf']:.2f} (allowed down to {o_old['pf'] - 0.1:.2f})",
         o_new["pf"] >= o_old["pf"] - 0.1),
        (f"3. whole channel: PF {b_new['pf']:.2f} vs today {b_old['pf']:.2f}; max drop {b_new['dd'] * 100:.1f}% <= 10%",
         b_new["pf"] >= b_old["pf"] and b_new["dd"] <= 0.10),
    ]
    print("\n=== pass criteria (fixed before the test) ===")
    for text, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {text}")
    print(f"\nVERDICT: {'PASS: go to 20 coins' if all(ok for _, ok in checks) else 'FAIL: stay on 10 coins'}")
