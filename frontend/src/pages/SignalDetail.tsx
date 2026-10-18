import clsx from "clsx";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Check, CheckCircle2, CircleDashed, CircleSlash, Copy } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "@/lib/api";
import { useLivePrice, useMeta } from "@/lib/queries";
import { duration, num, pair, pct, positionReturn, price, r, stamp, tz } from "@/lib/format";
import { useTheme } from "@/lib/theme";
import { Badge, Card, CardHeader, Empty, Skeleton, Stat } from "@/components/ui";
import { LevelBar, OutcomeBadge, PnL, SideBadge, StrategyChip, TargetPips, Trend, useNow } from "@/components/bits";
import { SignalChart } from "@/components/charts";
import { PositionCalculator } from "@/components/Calculator";
import type { Signal } from "@/lib/types";

function Row({ k, v, className }: { k: string; v: React.ReactNode; className?: string }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2 text-sm">
      <span className="text-muted">{k}</span>
      <span className={`num text-right ${className ?? ""}`}>{v}</span>
    </div>
  );
}

const EXIT_LABEL = { TP: "Final target hit", SL: "Stop hit", BE: "Rest closed at entry", TIME: "Time exit" } as const;

function Timeline({ s }: { s: Signal }) {
  const multi = s.targets.length > 1;
  const items: { t: string; label: string; note: string; pending?: boolean }[] = [
    { t: s.signal_open_at, label: "Signal candle opened", note: `${s.strategy} conditions evaluated at its close` },
    { t: s.entry_at, label: "Signal published · entry", note: `market entry at ${price(s.entry_price)}` },
  ];
  for (const t of s.targets) {
    if (!t.hit_at || (s.exit_reason === "TP" && t.n === s.targets.length && t.hit_at === s.exit_at)) continue;
    items.push({
      t: t.hit_at, label: multi ? `TP${t.n} hit` : "Target hit",
      note: `${multi ? `${num(t.size_pct, 0)}% closed at ` : "filled at "}${price(t.fill_price)} (${pct(t.pct)})${t.n === 1 && s.breakeven && multi ? " · stop moved to entry" : ""}`,
    });
  }
  if (s.exit_at) {
    items.push({ t: s.exit_at, label: s.exit_reason === "TP" && !multi ? "Target hit" : EXIT_LABEL[s.exit_reason!], note: `exit ${price(s.exit_price)} · net ${pct(s.pnl_net_pct)} for the whole position` });
  } else {
    items.push({ t: s.expires_at, label: "Time stop (pending)", note: "the open part is closed at market if neither the targets nor the stop are hit", pending: true });
  }
  return (
    <ol className="relative ml-2 border-l border-line">
      {items.map((it, i) => (
        <li key={i} className="mb-5 ml-5 last:mb-0">
          <span className={`absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full ${it.pending ? "bg-faint" : "bg-accent"}`} />
          <div className="text-sm font-medium">{it.label}</div>
          <div className="num text-xs text-faint">{stamp(it.t, true)} {tz()}</div>
          <div className="text-xs text-muted">{it.note}</div>
        </li>
      ))}
    </ol>
  );
}

/** TP1 / TP2 / TP3: price, distance, share of the position, and whether / when each was reached. */
function Targets({ s }: { s: Signal }) {
  const closed = s.status === "CLOSED";
  return (
    <div className={clsx("grid gap-3", s.targets.length === 3 ? "sm:grid-cols-3" : "sm:grid-cols-1")}>
      {s.targets.map((t) => {
        const hit = t.hit_at !== null;
        return (
          <div key={t.n} className={clsx("rounded-xl border p-3.5", hit ? "border-long/40 bg-long/5" : "border-line bg-raised/40")}>
            <div className="flex items-center justify-between">
              <span className="label">{s.targets.length > 1 ? `TP${t.n} · close ${num(t.size_pct, 0)}%` : "Target · close 100%"}</span>
              {hit ? <CheckCircle2 size={16} className="text-long" /> : closed ? <CircleSlash size={16} className="text-faint" /> : <CircleDashed size={16} className="text-faint" />}
            </div>
            <div className="num mt-1.5 text-lg font-semibold text-long">{price(t.price)}</div>
            <div className="num text-xs text-muted">{pct(t.pct)} · {num(s.atr ? Math.abs(t.price - s.entry_price) / s.atr : 0, 2)} ATR</div>
            <div className="num mt-2 text-2xs text-faint">
              {hit ? `hit ${stamp(t.hit_at, true)} ${tz()}${t.fill_price !== null && Math.abs(t.fill_price - t.price) > 1e-12 ? ` · filled ${price(t.fill_price)}` : ""}` : closed ? "not reached" : "pending"}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function SignalDetail() {
  const { id = "" } = useParams();
  const { theme } = useTheme();
  const { data: meta } = useMeta();
  const now = useNow(10_000);
  const [copied, setCopied] = useState(false);
  const { data: s, isLoading, error } = useQuery({ queryKey: ["signal", id], queryFn: () => api.signal(id), refetchInterval: 30_000 });
  const end = s ? new Date(Math.min(Date.now() + 86400e3, new Date(s.exit_at ?? s.expires_at).getTime() + 5 * 86400e3)).toISOString() : undefined;
  const { data: candles } = useQuery({
    queryKey: ["candles", s?.symbol, s?.id, s?.status],
    queryFn: () => api.candles(s!.symbol, 400, end),
    enabled: !!s,
  });
  const live = useLivePrice(s?.symbol ?? "", s?.last_price ?? null);

  if (isLoading) return <div className="space-y-4"><Skeleton className="h-10 w-72" /><Skeleton className="h-[420px]" /></div>;
  if (error || !s) return <Card><Empty title="Signal not found">It may not exist or is not published. <Link className="link" to="/signals">Back to signals</Link></Empty></Card>;

  const active = s.status === "ACTIVE";
  const last = active ? live : s.exit_price;
  const upnl = active && last ? positionReturn(s, last) : null;
  const held = ((s.exit_at ? new Date(s.exit_at).getTime() : now) - new Date(s.entry_at).getTime()) / 1000;
  const multi = s.targets.length > 1;
  const riskFree = s.breakeven && s.targets_hit > 0;
  const tps = multi ? s.targets.map((t) => `TP${t.n} ${price(t.price)} (${num(t.size_pct, 0)}%)`).join(" ") : `TP ${price(s.take_profit)}`;
  const copyText = `${s.side} ${s.symbol} (${s.strategy}) entry ${price(s.entry_price)} ${tps} SL ${price(s.stop_loss)}${multi && s.breakeven ? " · SL to entry after TP1" : ""} · exit by ${stamp(s.expires_at, true)} ${tz()}`;

  return (
    <div className="space-y-6">
      <Link to="/signals" className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink"><ArrowLeft size={14} /> Signals</Link>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">{pair(s.symbol)}</h1>
          <SideBadge side={s.side} />
          <StrategyChip code={s.strategy} full />
          <OutcomeBadge reason={s.exit_reason} pnl={s.pnl_net_pct} hits={s.targets_hit} total={s.targets.length} />
          {s.origin !== (meta?.demo ? "demo" : "live") && <Badge tone="warn">{s.origin}</Badge>}
        </div>
        <button className="btn" onClick={() => { navigator.clipboard?.writeText(copyText); setCopied(true); window.setTimeout(() => setCopied(false), 1500); }}>
          {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? "Copied" : "Copy levels"}
        </button>
      </div>

      <Card className="card-pad">
        <div className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Entry" value={price(s.entry_price)} sub={`${stamp(s.entry_at)} ${tz()}`} />
          <Stat label="Stop" value={riskFree && active ? price(s.stop_current) : price(s.stop_loss)}
            sub={riskFree && active ? <span className="text-long">moved to entry · risk-free</span> : `−${num(s.sl_pct)}% · ${s.sl_atr} ATR`} tone={riskFree && active ? undefined : "short"} />
          <Stat label={multi ? "Targets reached" : "Target"} value={multi ? <span className="inline-flex items-center gap-2">{s.targets_hit} / {s.targets.length} <TargetPips hit={s.targets_hit} total={s.targets.length} /></span> : price(s.take_profit)}
            sub={multi ? (s.breakeven ? "stop to entry after TP1" : "fixed stop") : `+${num(s.tp_pct)}% · ${s.tp_atr} ATR`} tone={multi ? undefined : "long"} />
          <Stat label={active ? "Last price" : "Exit"} value={price(last)} sub={active ? "live" : `${stamp(s.exit_at)} ${tz()}`} />
          <Stat label={active ? "Open P&L" : "Net result"} value={<PnL value={active ? upnl : s.pnl_net_pct} />} sub={active ? (s.targets_hit ? "incl. closed targets, before costs" : "before costs") : `${r(s.r_multiple)} · after costs`} />
          <Stat label={active ? "Time left" : "Held"} value={active ? duration((new Date(s.expires_at).getTime() - now) / 1000) : duration(held)} sub={`max ${s.max_bars} candles`} />
        </div>
        <div className="mt-5">
          <LevelBar entry={s.entry_price} sl={s.stop_loss} targets={s.targets.map((t) => t.price)} hit={s.targets_hit} riskFree={riskFree} last={last} />
          <div className="num mt-1 flex justify-between text-2xs text-faint">
            <span className={riskFree ? "line-through" : ""}>Stop {price(s.stop_loss)}</span><span>Entry {price(s.entry_price)}</span>
            <span>{multi ? `TP${s.targets.length}` : "Target"} {price(s.targets[s.targets.length - 1].price)}</span>
          </div>
        </div>
        <div className="mt-5"><Targets s={s} /></div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="4H chart" hint="Entry, targets and stop as published; markers show the signal candle, each target hit and the exit" />
          <div className="p-2 sm:p-3">{candles?.length ? <SignalChart candles={candles} signal={s} theme={theme} /> : <Skeleton className="h-[420px]" />}</div>
        </Card>
        <div className="space-y-6">
          <Card className="card-pad">
            <h2 className="text-sm font-semibold">Signal facts</h2>
            <div className="mt-2 divide-y divide-line/60">
              <Row k="Signal ID" v={`#${s.id}`} />
              <Row k="Strategy" v={`${s.strategy_name} (${s.strategy})`} />
              <Row k="Regime at signal" v={<span className="inline-flex items-center gap-2">BTC <Trend value={s.regime_btc} /> coin <Trend value={s.regime_coin} /></span>} />
              {s.model_prob !== null && <Row k="Model confidence" v={`${num(s.model_prob * 100, 1)}%`} />}
              <Row k="ATR(14) at signal" v={price(s.atr)} />
              <Row k="Reward : risk (TP1)" v={s.reward_risk ? `1 : ${num(1 / s.reward_risk, 1)}` : "—"} />
              <Row k="Best / worst excursion" v={<><span className="text-long">{pct(s.mfe_pct)}</span> / <span className="text-short">{pct(s.mae_pct)}</span></>} />
              <Row k="Expires" v={`${stamp(s.expires_at)} ${tz()}`} />
            </div>
          </Card>
          <Card className="card-pad">
            <h2 className="mb-4 text-sm font-semibold">Timeline</h2>
            <Timeline s={s} />
          </Card>
        </div>
      </div>

      <Card>
        <CardHeader title="Size this trade" hint="Risk-based sizing: the loss at the stop equals your chosen % of the account" />
        <div className="card-pad"><PositionCalculator entry={s.entry_price} stop={s.stop_loss} target={s.take_profit} targets={multi ? s.targets : undefined} defaultRisk={meta?.default_risk_pct} /></div>
      </Card>
    </div>
  );
}
