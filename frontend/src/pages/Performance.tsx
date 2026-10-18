import clsx from "clsx";
import { LineChart } from "lucide-react";
import { useState } from "react";
import { useEquity, useMeta, useMonthly, useStats } from "@/lib/queries";
import { monthLabel, num, pct, r } from "@/lib/format";
import { useTheme } from "@/lib/theme";
import type { Benchmark, Kpis } from "@/lib/types";
import { Card, CardHeader, Empty, Segmented, Skeleton, Stat } from "@/components/ui";
import { StrategyChip } from "@/components/bits";
import { EquityChart } from "@/components/charts";

function Compare({ k, b }: { k: Kpis; b: Benchmark }) {
  const rows: [string, number | null, number, (x: number | null) => string, boolean][] = [
    ["Win rate", k.win_rate, b.win_rate * 100, (x) => pct(x, 1, false), true],
    ["Break-even", k.breakeven_win_rate, b.breakeven_win_rate * 100, (x) => pct(x, 1, false), false],
    ["Profit factor", k.profit_factor, b.profit_factor, (x) => num(x), true],
    ["Net per signal", k.expectancy, b.net_pct, (x) => pct(x), true],
    ["Average win", k.avg_win, b.avg_win_pct, (x) => pct(x), true],
    ["Average loss", k.avg_loss === null ? null : -k.avg_loss, -b.avg_loss_pct, (x) => pct(x), true],
  ];
  if (b.tp2_rate !== undefined && b.tp3_rate !== undefined) {
    rows.push(["Reached TP2", k.tp2_rate, b.tp2_rate * 100, (x) => pct(x, 1, false), true],
              ["Reached TP3", k.tp3_rate, b.tp3_rate * 100, (x) => pct(x, 1, false), true]);
  }
  return (
    <table className="w-full text-sm">
      <thead><tr className="table-head"><th className="px-4 py-2 sm:px-5">Metric</th><th className="px-3 py-2 text-right">Live</th><th className="px-3 py-2 text-right">Backtest</th><th className="px-4 py-2 text-right sm:px-5">Δ</th></tr></thead>
      <tbody>
        {rows.map(([label, live, bt, f, higherBetter]) => {
          const d = live === null ? null : live - bt;
          return (
            <tr key={label} className="table-row">
              <td className="px-4 py-2.5 text-muted sm:px-5">{label}</td>
              <td className="num px-3 py-2.5 text-right">{f(live)}</td>
              <td className="num px-3 py-2.5 text-right text-muted">{f(bt)}</td>
              <td className={clsx("num px-4 py-2.5 text-right sm:px-5", d === null ? "text-faint" : (d >= 0) === higherBetter ? "text-long" : "text-short")}>
                {d === null ? "—" : `${d > 0 ? "+" : ""}${d.toFixed(2).replace("-", "−")}`}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function OutcomeMix({ k }: { k: Kpis }) {
  const total = k.signals || 1;
  const parts = [
    { key: "TP", label: "All targets", color: "bg-long", n: k.by_reason.TP ?? 0 },
    { key: "BE", label: "TP1+, rest at entry", color: "bg-long/50", n: k.by_reason.BE ?? 0 },
    { key: "TIME", label: "Time", color: "bg-warn", n: k.by_reason.TIME ?? 0 },
    { key: "SL", label: "Stop", color: "bg-short", n: k.by_reason.SL ?? 0 },
  ];
  const reach = [k.tp1_rate, k.tp2_rate, k.tp3_rate];
  return (
    <div>
      <div className="flex h-2.5 overflow-hidden rounded-full bg-raised ring-1 ring-line">
        {parts.map((p) => <div key={p.key} className={p.color} style={{ width: `${(p.n / total) * 100}%` }} />)}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-x-2 gap-y-3">
        {parts.map((p) => (
          <div key={p.key}>
            <div className="flex items-center gap-1.5 text-xs text-muted"><span className={clsx("h-2 w-2 rounded-full", p.color)} />{p.label}</div>
            <div className="num mt-0.5 text-sm">{p.n} <span className="text-xs text-faint">{num((p.n / total) * 100, 0)}%</span></div>
          </div>
        ))}
      </div>
      {k.signals > 0 && (
        <div className="mt-4 border-t border-line/60 pt-3">
          <div className="label">Targets reached</div>
          <div className="mt-2 space-y-1.5">
            {reach.map((x, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                <span className="num w-8 text-muted">TP{i + 1}</span>
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-raised ring-1 ring-line"><div className="h-full bg-long/80" style={{ width: `${x ?? 0}%` }} /></div>
                <span className="num w-12 text-right">{pct(x, 0, false)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function Performance() {
  const { data: meta } = useMeta();
  const { theme } = useTheme();
  const [strategy, setStrategy] = useState("ALL");
  const [days, setDays] = useState<number | 0>(0);
  const [risk, setRisk] = useState(0.5);
  const [origin, setOrigin] = useState<"default" | "all">("default");
  const q = { strategy, days: days || null, origin };
  const { data: stats, isLoading } = useStats(q);
  const { data: eq } = useEquity({ ...q, risk });
  const { data: months } = useMonthly({ strategy, origin });
  const k = stats?.kpis;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Performance</h1>
          <p className="mt-1 text-sm text-muted">Net of fees and slippage (entry 0.07%, target 0.02% maker, stop 0.08%). Win = net result above zero.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Segmented value={strategy} onChange={setStrategy} size="sm"
            options={[{ value: "ALL", label: "All" }, ...(meta?.strategies ?? []).map((s) => ({ value: s.code, label: `${s.letter} · ${s.name}` }))]} />
          <Segmented value={days} onChange={setDays} size="sm"
            options={[{ value: 30, label: "30D" }, { value: 90, label: "90D" }, { value: 365, label: "1Y" }, { value: 0, label: "All" }]} />
          <Segmented value={origin} onChange={setOrigin} size="sm"
            options={[{ value: "default", label: "Real-time" }, { value: "all", label: "+ Backfill" }]} />
        </div>
      </div>

      <Card className="card-pad">
        {isLoading || !k ? <Skeleton className="h-28" /> : (
          <div className="grid grid-cols-2 gap-x-6 gap-y-6 sm:grid-cols-4">
            <Stat label="Closed signals" value={k.signals.toLocaleString()} sub={k.signals_per_day ? `${num(k.signals_per_day)} per day` : "—"} />
            <Stat label="Win rate" value={pct(k.win_rate, 1, false)} sub={`break-even ${pct(k.breakeven_win_rate, 1, false)}`} />
            <Stat label="Profit factor" value={num(k.profit_factor)} sub="gross wins ÷ gross losses" />
            <Stat label="Net per signal" value={pct(k.expectancy)} tone={(k.expectancy ?? 0) < 0 ? "short" : undefined} sub={`avg ${r(k.avg_r)}`} />
            <Stat label="Average win" value={pct(k.avg_win)} tone="long" />
            <Stat label="Average loss" value={k.avg_loss === null ? "—" : pct(-k.avg_loss)} tone="short" />
            <Stat label="Total" value={r(k.total_r, 1)} sub="sum of R multiples" />
            <Stat label="Longest losing streak" value={k.max_consecutive_losses} />
          </div>
        )}
      </Card>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader
            title="Account curve"
            hint={eq && eq.points.length ? `Following every signal at ${risk}% risk: ${pct(eq.total_return_pct)} · max drawdown ${pct(-eq.max_drawdown_pct)}` : "Compounded, every signal sized to risk a fixed % of equity"}
            actions={<Segmented value={risk} onChange={setRisk} size="sm" options={[{ value: 0.25, label: "0.25%" }, { value: 0.5, label: "0.5%" }, { value: 1, label: "1%" }]} />}
          />
          <div className="p-2 sm:p-3">
            {eq && eq.points.length > 1 ? <EquityChart data={eq} theme={theme} /> : (
              <Empty icon={<LineChart size={28} />} title="Not enough closed signals yet">The curve appears after the first results. The backtest benchmark is shown alongside.</Empty>
            )}
          </div>
        </Card>
        <div className="space-y-6">
          <Card>
            <CardHeader title="Live vs backtest" hint={stats ? `Backtest: ${stats.benchmark.period}, ${stats.benchmark.signals.toLocaleString()} out-of-sample signals` : undefined} />
            {k && stats ? <Compare k={k} b={stats.benchmark} /> : <div className="p-5"><Skeleton className="h-40" /></div>}
          </Card>
          <Card className="card-pad">
            <h2 className="mb-3 text-sm font-semibold">How signals ended</h2>
            {k ? <OutcomeMix k={k} /> : <Skeleton className="h-10" />}
          </Card>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="By strategy" />
          <table className="w-full text-sm">
            <thead><tr className="table-head"><th className="px-4 py-2 sm:px-5">Strategy</th><th className="px-3 py-2 text-right">Signals</th><th className="px-3 py-2 text-right">Win rate</th><th className="px-3 py-2 text-right">PF</th><th className="px-3 py-2 text-right">Net/signal</th><th className="px-4 py-2 text-right sm:px-5">Total</th></tr></thead>
            <tbody>
              {meta?.strategies.map((s) => {
                const x = stats?.by_strategy[s.code];
                return (
                  <tr key={s.code} className="table-row">
                    <td className="px-4 py-2.5 sm:px-5"><StrategyChip code={s.code} /></td>
                    <td className="num px-3 py-2.5 text-right">{x?.signals ?? 0}</td>
                    <td className="num px-3 py-2.5 text-right">{pct(x?.win_rate, 1, false)}</td>
                    <td className="num px-3 py-2.5 text-right">{num(x?.profit_factor)}</td>
                    <td className="num px-3 py-2.5 text-right">{pct(x?.expectancy)}</td>
                    <td className="num px-4 py-2.5 text-right sm:px-5">{r(x?.total_r, 1)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
        <Card>
          <CardHeader title="Monthly" hint="By exit month" />
          {!months?.length ? <Empty title="No closed months yet" /> : (
            <div className="max-h-[360px] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-surface"><tr className="table-head"><th className="px-4 py-2 sm:px-5">Month</th><th className="px-3 py-2 text-right">Signals</th><th className="px-3 py-2 text-right">Win rate</th><th className="px-3 py-2 text-right">PF</th><th className="px-4 py-2 text-right sm:px-5">Total</th></tr></thead>
                <tbody>
                  {[...months].reverse().map((m) => (
                    <tr key={m.month} className="table-row">
                      <td className="px-4 py-2.5 sm:px-5">{monthLabel(m.month)}</td>
                      <td className="num px-3 py-2.5 text-right">{m.signals}</td>
                      <td className="num px-3 py-2.5 text-right">{pct(m.win_rate, 1, false)}</td>
                      <td className="num px-3 py-2.5 text-right">{num(m.profit_factor)}</td>
                      <td className={clsx("num px-4 py-2.5 text-right sm:px-5", m.total_r >= 0 ? "text-long" : "text-short")}>{r(m.total_r, 1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
