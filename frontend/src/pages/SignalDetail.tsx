import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Check, Copy } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "@/lib/api";
import { useLivePrice, useMeta } from "@/lib/queries";
import { duration, num, pair, pct, price, r, unrealized, utc } from "@/lib/format";
import { useTheme } from "@/lib/theme";
import { Badge, Card, CardHeader, Empty, Skeleton, Stat } from "@/components/ui";
import { LevelBar, OutcomeBadge, PnL, SideBadge, StrategyChip, Trend, useNow } from "@/components/bits";
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

function Timeline({ s }: { s: Signal }) {
  const items = [
    { t: s.signal_open_at, label: "Signal candle opened", note: `${s.strategy} conditions evaluated at its close` },
    { t: s.entry_at, label: "Signal published · entry", note: `market entry at ${price(s.entry_price)}` },
    s.exit_at
      ? { t: s.exit_at, label: { TP: "Target hit", SL: "Stop hit", TIME: "Time exit" }[s.exit_reason!], note: `exit ${price(s.exit_price)} · net ${pct(s.pnl_net_pct)}` }
      : { t: s.expires_at, label: "Time stop (pending)", note: "closed at market if neither level is hit" },
  ];
  return (
    <ol className="relative ml-2 border-l border-line">
      {items.map((it, i) => (
        <li key={i} className="mb-5 ml-5 last:mb-0">
          <span className={`absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full ${i === 2 && !s.exit_at ? "bg-faint" : "bg-accent"}`} />
          <div className="text-sm font-medium">{it.label}</div>
          <div className="num text-xs text-faint">{utc(it.t, true)} UTC</div>
          <div className="text-xs text-muted">{it.note}</div>
        </li>
      ))}
    </ol>
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
  const upnl = active && last ? unrealized(s.side, s.entry_price, last) : null;
  const held = ((s.exit_at ? new Date(s.exit_at).getTime() : now) - new Date(s.entry_at).getTime()) / 1000;
  const copyText = `${s.side} ${s.symbol} (${s.strategy}) entry ${price(s.entry_price)} TP ${price(s.take_profit)} SL ${price(s.stop_loss)} exit by ${utc(s.expires_at, true)} UTC`;

  return (
    <div className="space-y-6">
      <Link to="/signals" className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink"><ArrowLeft size={14} /> Signals</Link>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">{pair(s.symbol)}</h1>
          <SideBadge side={s.side} />
          <StrategyChip code={s.strategy} full />
          <OutcomeBadge reason={s.exit_reason} pnl={s.pnl_net_pct} />
          {s.origin !== (meta?.demo ? "demo" : "live") && <Badge tone="warn">{s.origin}</Badge>}
        </div>
        <button className="btn" onClick={() => { navigator.clipboard?.writeText(copyText); setCopied(true); window.setTimeout(() => setCopied(false), 1500); }}>
          {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? "Copied" : "Copy levels"}
        </button>
      </div>

      <Card className="card-pad">
        <div className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Entry" value={price(s.entry_price)} sub={`${utc(s.entry_at)} UTC`} />
          <Stat label="Target" value={price(s.take_profit)} sub={`+${num(s.tp_pct)}% · ${s.tp_atr} ATR`} tone="long" />
          <Stat label="Stop" value={price(s.stop_loss)} sub={`−${num(s.sl_pct)}% · ${s.sl_atr} ATR`} tone="short" />
          <Stat label={active ? "Last price" : "Exit"} value={price(last)} sub={active ? "live" : `${utc(s.exit_at)} UTC`} />
          <Stat label={active ? "Open P&L" : "Net result"} value={<PnL value={active ? upnl : s.pnl_net_pct} />} sub={active ? "before costs" : `${r(s.r_multiple)} · after costs`} />
          <Stat label={active ? "Time left" : "Held"} value={active ? duration((new Date(s.expires_at).getTime() - now) / 1000) : duration(held)} sub={`max ${s.max_bars} candles`} />
        </div>
        <div className="mt-5">
          <LevelBar entry={s.entry_price} tp={s.take_profit} sl={s.stop_loss} last={last} />
          <div className="num mt-1 flex justify-between text-2xs text-faint"><span>Stop {price(s.stop_loss)}</span><span>Entry {price(s.entry_price)}</span><span>Target {price(s.take_profit)}</span></div>
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="4H chart" hint="Entry, target and stop as published; markers show the signal candle and the exit" />
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
              <Row k="Reward : risk" v={s.reward_risk ? `1 : ${num(1 / s.reward_risk, 1)}` : "—"} />
              <Row k="Best / worst excursion" v={<><span className="text-long">{pct(s.mfe_pct)}</span> / <span className="text-short">{pct(s.mae_pct)}</span></>} />
              <Row k="Expires" v={`${utc(s.expires_at)} UTC`} />
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
        <div className="card-pad"><PositionCalculator entry={s.entry_price} stop={s.stop_loss} target={s.take_profit} defaultRisk={meta?.default_risk_pct} /></div>
      </Card>
    </div>
  );
}
