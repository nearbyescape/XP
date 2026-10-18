import clsx from "clsx";
import { ArrowRight, Radar } from "lucide-react";
import { Link } from "react-router-dom";
import { useMeta, useRegime, useSignals, useStats } from "@/lib/queries";
import { base, num, pct, priceShort, r, utc } from "@/lib/format";
import type { Kpis, StrategyMeta } from "@/lib/types";
import { Badge, Card, CardHeader, Empty, Skeleton, Stat } from "@/components/ui";
import { OutcomeBadge, PnL, SideBadge, STRATEGY_STYLE, Trend } from "@/components/bits";
import { ActiveSignalsTable } from "@/components/SignalsTable";

function ModeBadge({ s }: { s: StrategyMeta }) {
  if (s.auto_paused) return <Badge tone="warn" title={s.pause_reason ?? ""}>Paused</Badge>;
  if (s.mode === "live") return <Badge tone="long">Live</Badge>;
  if (s.mode === "shadow") return <Badge tone="accent">Shadow</Badge>;
  return <Badge>Off</Badge>;
}

function KpiStrip() {
  const { data: meta } = useMeta();
  const { data: stats, isLoading } = useStats({});
  const k = stats?.kpis;
  const b = meta?.book_benchmark;
  if (isLoading || !k || !b) return <Card className="card-pad"><Skeleton className="h-16 w-full" /></Card>;
  const empty = k.signals === 0;
  return (
    <Card className="card-pad">
      <div className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Win rate" value={pct(k.win_rate, 1, false)} sub={empty ? `backtest ${num(b.win_rate * 100, 1)}%` : `break-even ${pct(k.breakeven_win_rate, 1, false)}`} />
        <Stat label="Profit factor" value={num(k.profit_factor)} sub={`backtest ${num(b.profit_factor)}`} />
        <Stat label="Net per signal" value={pct(k.expectancy)} tone={(k.expectancy ?? 0) >= 0 ? undefined : "short"} sub={`backtest +${num(b.net_pct)}%`} />
        <Stat label="Total R" value={r(k.total_r, 1)} sub={k.avg_r !== null ? `avg ${r(k.avg_r)} / signal` : "fixed-risk units"} />
        <Stat label="Closed signals" value={k.signals.toLocaleString()} sub={stats.first_entry_at ? `since ${utc(stats.first_entry_at, true)}` : "none yet"} />
        <Stat label="Open now" value={stats.open_signals} sub={`${meta.universe.length} markets · ${meta.strategies.filter((s) => s.mode === "live" && !s.auto_paused).length} live strategies`} />
      </div>
    </Card>
  );
}

function RegimeCard() {
  const { data } = useRegime();
  const { data: meta } = useMeta();
  const items = data?.items ?? {};
  const btc = items.BTCUSDT;
  const label = { 1: "Bull regime", "-1": "Bear regime", 0: "Neutral regime" } as Record<string, string>;
  const note = { 1: "Dip-buys active on coins in up-trends · shorts paused", "-1": "Rally-shorts active on coins in down-trends · longs paused", 0: "BTC has no clear trend · rule signals are rare" } as Record<string, string>;
  return (
    <Card className="flex h-full flex-col">
      <CardHeader title="Market regime" hint="4H trend: close vs EMA200 and its 4-day slope" />
      {!btc ? (
        <div className="p-5"><Skeleton className="h-40 w-full" /></div>
      ) : (
        <div className="flex flex-1 flex-col p-4 sm:p-5">
          <div className="flex items-center gap-3">
            <div className={clsx("grid h-11 w-11 place-items-center rounded-xl ring-1", btc.coin === 1 ? "bg-long/10 ring-long/30" : btc.coin === -1 ? "bg-short/10 ring-short/30" : "bg-raised ring-line")}>
              <Trend value={btc.coin} className="scale-150" />
            </div>
            <div>
              <div className="text-base font-semibold">{label[String(btc.coin)]}</div>
              <div className="text-xs text-muted">{note[String(btc.coin)]}</div>
            </div>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-1.5">
            {(meta?.universe ?? Object.keys(items)).filter((s) => items[s]).map((s) => {
              const it = items[s];
              return (
                <div key={s} className="flex items-center justify-between gap-2 rounded-lg border border-line/70 bg-raised/50 px-2.5 py-1.5 text-xs">
                  <span className="flex items-center gap-1.5 font-semibold"><Trend value={it.coin} />{base(s)}</span>
                  <span className="num whitespace-nowrap text-right">
                    <span className="text-muted">{priceShort(it.close)}</span>{" "}
                    <span className={(it.change_24h ?? 0) >= 0 ? "text-long" : "text-short"}>{pct((it.change_24h ?? 0) * 100, 1)}</span>
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </Card>
  );
}

function StrategyCard({ s, k }: { s: StrategyMeta; k?: Kpis }) {
  const style = STRATEGY_STYLE[s.code];
  return (
    <Card className="card-pad flex flex-col">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className={clsx("grid h-9 w-9 place-items-center rounded-lg border text-sm font-bold", style.chip)}>{s.letter}</div>
          <div>
            <div className="font-semibold">{s.name}</div>
            <div className="num text-2xs text-faint">{s.code} · {s.kind === "model" ? "LightGBM" : "rules"}</div>
          </div>
        </div>
        <ModeBadge s={s} />
      </div>
      <p className="mt-3 line-clamp-2 text-sm text-muted">{s.summary}</p>
      <div className="mt-4 grid grid-cols-3 gap-3 border-t border-line pt-3">
        <Stat label="Win rate" value={k?.signals ? pct(k.win_rate, 1, false) : "—"} className="[&_.num]:text-base" />
        <Stat label="PF" value={k?.signals ? num(k.profit_factor) : "—"} className="[&_.num]:text-base" />
        <Stat label="Signals" value={k?.signals ?? 0} className="[&_.num]:text-base" />
      </div>
      <div className="mt-3 text-xs text-faint">
        Backtest 2022–26: <span className="num text-muted">{num(s.benchmark.win_rate * 100, 1)}% · PF {num(s.benchmark.profit_factor)} · +{num(s.benchmark.net_pct)}%/signal</span>
      </div>
    </Card>
  );
}

function RecentResults() {
  const { data, isLoading } = useSignals({ status: "closed", limit: 8 });
  return (
    <Card className="flex h-full flex-col">
      <CardHeader title="Latest results" actions={<Link to="/signals?tab=history" className="text-xs text-accent hover:underline">Full ledger</Link>} />
      {isLoading ? (
        <div className="space-y-2 p-5">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-8" />)}</div>
      ) : !data?.items.length ? (
        <Empty title="No closed signals yet">Results appear here as soon as the first signal hits its target, stop or time limit.</Empty>
      ) : (
        <ul className="divide-y divide-line/60">
          {data.items.map((s) => (
            <li key={s.id}>
              <Link to={`/signals/${s.id}`} className="flex items-center gap-3 px-4 py-2.5 text-sm transition hover:bg-raised/60 sm:px-5">
                <SideBadge side={s.side} />
                <span className="w-14 font-semibold">{base(s.symbol)}</span>
                <span className={clsx("num grid h-5 w-5 place-items-center rounded border text-2xs font-bold", STRATEGY_STYLE[s.strategy]?.chip)} title={s.strategy}>
                  {STRATEGY_STYLE[s.strategy]?.letter}
                </span>
                <span className="ml-auto flex items-center gap-2">
                  <span className="flex w-16 justify-end"><OutcomeBadge reason={s.exit_reason} pnl={s.pnl_net_pct} hits={s.targets_hit} total={s.targets.length} /></span>
                  <PnL value={s.pnl_net_pct} className="w-16 text-right" />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export default function Overview() {
  const { data: meta } = useMeta();
  const { data: active, isLoading } = useSignals({ status: "active", limit: 100 });
  const { data: stats } = useStats({});
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Signal desk</h1>
          <p className="mt-1 text-sm text-muted">
            Three validated 4H strategies across {meta?.universe.length ?? 10} markets · evaluated at every 4H close (UTC) · every result published.
          </p>
        </div>
        <Link to="/strategies" className="btn">How the strategies work <ArrowRight size={14} /></Link>
      </div>

      <KpiStrip />

      <Card>
        <CardHeader
          title={<span className="flex items-center gap-2">Active signals <span className="num rounded-md bg-raised px-1.5 text-xs text-muted">{active?.total ?? 0}</span></span>}
          hint="Live price between stop (left) and target (right); updates every few seconds"
          actions={<Link to="/signals" className="text-xs text-accent hover:underline">All signals</Link>}
        />
        {!isLoading && !active?.items.length ? (
          <Empty icon={<Radar size={28} />} title="No open signals right now">
            The engine scores every market at each 4H close. A signal is published only when a strategy's conditions are met, so quiet periods are normal, especially when BTC has no clear trend.
          </Empty>
        ) : (
          <ActiveSignalsTable rows={active?.items ?? []} loading={isLoading} />
        )}
      </Card>

      <div className="grid gap-6 lg:grid-cols-3">
        <RegimeCard />
        <RecentResults />
        <Card>
          <CardHeader title="How to use a signal" hint="Four rules that reproduce the published results" />
          <ol className="space-y-2.5 p-4 text-sm text-muted sm:p-5">
            {[
              ["Enter at market", "Signals publish seconds after a 4H close. The entry is the new candle's open."],
              ["Three targets as limits", "TP1, TP2 and TP3 rest as limit orders for 50%, 30% and 20% of the position (maker fees); the stop is a stop-market order."],
              ["Size by the stop", `Risk a fixed ${meta?.default_risk_pct ?? 0.5}% of equity per signal and keep exposure at 1×. The calculator does the maths.`],
              ["Stop to entry after TP1", "Once TP1 fills, move the stop to the entry price: the rest runs risk-free. Close anything still open at the expiry. Every step is logged here and in Telegram."],
            ].map(([t, d], i) => (
              <li key={t} className="flex gap-3 rounded-lg border border-line/70 bg-raised/40 p-3">
                <span className="num grid h-6 w-6 shrink-0 place-items-center rounded-md bg-accent/15 text-xs font-semibold text-accent">{i + 1}</span>
                <span><span className="font-medium text-ink">{t}.</span> {d}</span>
              </li>
            ))}
          </ol>
        </Card>
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        {meta?.strategies.map((s) => <StrategyCard key={s.code} s={s} k={stats?.by_strategy[s.code]} />)}
      </div>
    </div>
  );
}
