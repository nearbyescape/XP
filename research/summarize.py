"""Collate every grid in results/ into the funnel table used by the report.

Pre-registered selection rule (applied to IN-SAMPLE data only):
    win rate >= 80%, profit factor >= 1.2, >= 150 trades (4h) / 60 (1d) / 300 (1h, 15m)
"Survives OOS" = the same parameter set also shows win rate >= 80% and PF >= 1.15
on the untouched out-of-sample period.

    python research/summarize.py   -> results/summary_funnel.csv + results/summary_funnel.md

Grid naming: grid_<timeframe>_<cost>[_<subset>].csv, where cost "cost0.0007" = every fill taker
0.07% and "pro" = maker take-profit model (see COST_MODELS in run_research.py).
"""

from __future__ import annotations

import glob
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")


def tf_and_cost(name: str) -> tuple[str, str]:
    parts = os.path.basename(name).replace(".gz", "").replace(".csv", "").split("_")
    return parts[1], "taker" if parts[2].startswith("cost") else parts[2]


def main():
    rows = []
    # fresh runs write results/grid_*.csv; the committed copies live in results/grids/*.csv.gz
    paths = {os.path.basename(p).replace(".gz", ""): p
             for p in sorted(glob.glob(os.path.join(RES, "grids", "grid_*.csv.gz")))}
    paths.update({os.path.basename(p): p for p in glob.glob(os.path.join(RES, "grid_*.csv"))})
    for path in sorted(paths.values(), key=os.path.basename):
        tf, cost = tf_and_cost(path)
        g = pd.read_csv(path)
        min_trades = {"4h": 150, "1d": 60}.get(tf, 300)
        for strat, d in g.groupby("strategy"):
            q = d[(d.is_win_rate >= 0.80) & (d.is_profit_factor >= 1.2) & (d.is_trades >= min_trades)]
            ok = q[(q.oos_win_rate >= 0.80) & (q.oos_profit_factor >= 1.15)]
            best = q.sort_values("is_t_stat", ascending=False).head(1)
            rows.append({
                "timeframe": tf, "cost_model": cost, "strategy": strat, "configs": len(d),
                "is_wr80_configs": int((d.is_win_rate >= 0.8).sum()),
                "is_qualified": len(q), "oos_survivors": len(ok),
                "median_oos_expectancy_pct": round(d.oos_expectancy_pct.median(), 3),
                "best_is_oos_wr": round(best.oos_win_rate.iloc[0], 3) if len(best) else None,
                "best_is_oos_pf": round(best.oos_profit_factor.iloc[0], 3) if len(best) else None,
                "best_is_params": best.params.iloc[0] if len(best) else "",
            })
    out = pd.DataFrame(rows).drop_duplicates(["timeframe", "cost_model", "strategy"], keep="last")
    out.to_csv(os.path.join(RES, "summary_funnel.csv"), index=False)
    with open(os.path.join(RES, "summary_funnel.md"), "w") as fh:
        fh.write(out.drop(columns=["best_is_params"]).to_markdown(index=False))
    print(out.drop(columns=["best_is_params"]).to_string(index=False))


if __name__ == "__main__":
    main()
