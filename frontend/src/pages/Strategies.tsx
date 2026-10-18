import clsx from "clsx";
import { useMeta } from "@/lib/queries";
import { num } from "@/lib/format";
import { Badge, Card, Skeleton } from "@/components/ui";
import { STRATEGY_STYLE } from "@/components/bits";

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
          period it never saw, net of fees. Three survived. All run on the 4H chart with a small fixed target and a wider stop. That gives
          a high hit rate, but the edge is the margin above the break-even hit rate, not the hit rate itself.
        </p>
      </div>

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
            <li>• Average win ≈ +1.2%, average loss ≈ −7%: about one stop for every eight targets.</li>
            <li>• Losing streaks of 8–11 signals and rough quarters (win rate near 57%) occurred in the backtest.</li>
            <li>• At 0.5% risk per signal the backtest drawdown peaked at 13.8%. At 1% it would have roughly doubled.</li>
            <li>• Spot-exchange fees (0.1% per side) remove most of the edge. Use low-fee perpetual futures at 1×.</li>
            <li>• A strategy pauses automatically if its last 150 signals fall below an 82% win rate or a 0.75 profit factor.</li>
          </ul>
        </Card>
      </div>
    </div>
  );
}
