import clsx from "clsx";
import { ShieldCheck } from "lucide-react";
import { useMeta } from "@/lib/queries";
import { num } from "@/lib/format";
import type { Benchmark, StrategyMeta } from "@/lib/types";
import { Badge, Card, Skeleton } from "@/components/ui";
import { STRATEGY_STYLE } from "@/components/bits";

/** TP1 / TP2 / TP3: where each target sits, how much it closes and how often it was reached. */
function ExitPlan({ s, b }: { s: StrategyMeta; b: Benchmark }) {
  const rates = [b.tp1_rate, b.tp2_rate, b.tp3_rate];
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line p-5">
        <div>
          <h2 className="text-sm font-semibold">Exit plan: three targets, then a risk-free runner</h2>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            Every signal carries three take-profit limits measured in ATR(14), the average 4H range of the coin, so the distances adapt
            to each coin's volatility. TP1 is the validated target; TP2 and TP3 let part of the position run.
          </p>
        </div>
        {s.breakeven && <Badge tone="long"><ShieldCheck size={12} /> Stop to entry after TP1</Badge>}
      </div>
      <div className="grid gap-px bg-line/60 sm:grid-cols-3">
        {s.targets_atr.map((k, i) => (
          <div key={i} className="bg-surface p-5">
            <div className="flex items-baseline justify-between">
              <span className="text-lg font-semibold">TP{i + 1}</span>
              <span className="num text-sm text-muted">{k} × ATR</span>
            </div>
            <div className="num mt-3 text-3xl font-semibold">{num(s.target_sizes[i] * 100, 0)}%</div>
            <div className="text-xs text-muted">of the position closed</div>
            <div className="mt-4 flex items-center gap-2 text-xs">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-raised ring-1 ring-line"><div className="h-full bg-long/80" style={{ width: `${(rates[i] ?? 0) * 100}%` }} /></div>
              <span className="num w-24 text-right text-muted">{rates[i] !== undefined ? `${num(rates[i]! * 100, 1)}% reached` : "—"}</span>
            </div>
          </div>
        ))}
      </div>
      <p className="border-t border-line px-5 py-3 text-xs text-muted">
        Backtest {b.period}: a signal that reaches TP1 ends at or above break-even, so the win rate equals the TP1 hit rate. Compared with a single
        target, the plan keeps the same win rate and return per signal while about {b.tp2_rate !== undefined ? num(b.tp2_rate * 100, 0) : "45"}% of
        signals also reach TP2.
      </p>
    </Card>
  );
}

export default function Strategies() {
  const { data: meta } = useMeta();
  if (!meta) return <Skeleton className="h-96" />;
  const b = meta.book_benchmark;
  return (
    <div className="space-y-8">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight">Strategies & methodology</h1>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          About 33,000 strategy variants were backtested on Binance candles from 2017 to 2026. Each was tuned on one period and judged on a later
          period it never saw, net of fees. Three survived. All run on the 4H chart with a small first target and a wider stop. That gives
          a high hit rate, but the edge is the margin above the break-even hit rate, not the hit rate itself.
        </p>
      </div>

      <ExitPlan s={meta.strategies[0]} b={b} />

      <Card className="card-pad">
        <div className="label">Combined book · out-of-sample {b.period}</div>
        <div className="mt-3 grid grid-cols-2 gap-6 sm:grid-cols-3 lg:grid-cols-6">
          {[
            ["Signals", b.signals.toLocaleString()],
            ["Win rate", `${num(b.win_rate * 100, 1)}%`],
            ["Break-even", `${num(b.breakeven_win_rate * 100, 1)}%`],
            ["Profit factor", num(b.profit_factor)],
            ["Net / signal", `+${num(b.net_pct)}%`],
            ["CAGR @ 0.5% risk", b.cagr_at_half_pct_risk ? `+${num(b.cagr_at_half_pct_risk * 100, 1)}%` : "—"],
          ].map(([k, v]) => (
            <div key={k}><div className="label">{k}</div><div className="num mt-1.5 text-xl font-semibold">{v}</div></div>
          ))}
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-3">
        {meta.strategies.map((s) => {
          const st = STRATEGY_STYLE[s.code];
          return (
            <Card key={s.code} className="flex flex-col">
              <div className="border-b border-line p-5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className={clsx("grid h-10 w-10 place-items-center rounded-lg border text-base font-bold", st.chip)}>{s.letter}</div>
                    <div>
                      <div className="font-semibold">{s.name}</div>
                      <div className="num text-xs text-faint">{s.code}</div>
                    </div>
                  </div>
                  <Badge tone={s.kind === "model" ? "accent" : "neutral"}>{s.kind === "model" ? "Machine learning" : "Rule-based"}</Badge>
                </div>
                <p className="mt-4 text-sm leading-relaxed text-muted">{s.summary}</p>
              </div>
              <div className="flex-1 p-5">
                <div className="label">Rules</div>
                <pre className="num mt-2 whitespace-pre-wrap rounded-lg border border-line bg-raised/60 p-3 text-[12px] leading-relaxed text-ink">{s.rules}</pre>
                <div className="label mt-5">Out-of-sample backtest · {s.benchmark.period}</div>
                <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                  {[
                    ["Signals", s.benchmark.signals.toLocaleString()],
                    ["Win rate", `${num(s.benchmark.win_rate * 100, 1)}%`],
                    ["Break-even", `${num(s.benchmark.breakeven_win_rate * 100, 1)}%`],
                    ["Profit factor", num(s.benchmark.profit_factor)],
                    ["Avg win", `+${num(s.benchmark.avg_win_pct)}%`],
                    ["Avg loss", `−${num(s.benchmark.avg_loss_pct)}%`],
                    ...(s.benchmark.tp2_rate !== undefined && s.benchmark.tp3_rate !== undefined
                      ? [["Reached TP2", `${num(s.benchmark.tp2_rate * 100, 1)}%`], ["Reached TP3", `${num(s.benchmark.tp3_rate * 100, 1)}%`]]
                      : []),
                  ].map(([k, v]) => (
                    <div key={k} className="flex justify-between border-b border-line/50 py-1"><dt className="text-muted">{k}</dt><dd className="num">{v}</dd></div>
                  ))}
                </dl>
              </div>
            </Card>
          );
        })}
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="card-pad">
          <h2 className="text-sm font-semibold">Why a market-regime gate</h2>
          <p className="mt-2 text-sm leading-relaxed text-muted">
            A and B only buy dips when both the coin and BTC are in a 4H up-trend, and only sell rallies when both are in a down-trend.
            With the same entry rules and no gate, 0–18% of tested settings were profitable out-of-sample. With the gate, 82% were. Fading a move against the
            prevailing trend is where mean-reversion strategies lose money.
          </p>
        </Card>
        <Card className="card-pad">
          <h2 className="text-sm font-semibold">Risk you should expect</h2>
          <ul className="mt-2 space-y-1.5 text-sm text-muted">
            <li>• Average win ≈ +1.2%, average loss ≈ −7%: about one stop for every eight signals that reach TP1.</li>
            <li>• Losing streaks of 8–11 signals and rough quarters (win rate near 57%) occurred in the backtest.</li>
            <li>• At 0.5% risk per signal the backtest drawdown peaked at {b.max_dd_at_half_pct_risk ? `${num(b.max_dd_at_half_pct_risk * 100, 1)}%` : "≈14%"}. At 1% it would have roughly doubled.</li>
            <li>• Losses only come from signals stopped before TP1. After TP1 the stop sits at entry, so the rest of the trade can no longer lose.</li>
            <li>• Spot-exchange fees (0.1% per side) remove most of the edge. Use low-fee perpetual futures at 1×.</li>
            <li>• A strategy pauses automatically if its last 150 signals fall below an 82% win rate or a 0.75 profit factor.</li>
          </ul>
        </Card>
      </div>
    </div>
  );
}
