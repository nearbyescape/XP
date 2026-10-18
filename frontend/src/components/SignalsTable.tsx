import clsx from "clsx";
import { ChevronRight, Clock3 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { Signal } from "@/lib/types";
import { duration, pair, price, r, unrealized, utc } from "@/lib/format";
import { useMeta, usePrices } from "@/lib/queries";
import { useLive } from "@/lib/live";
import { LevelBar, OutcomeBadge, PnL, SideBadge, StrategyChip, useNow } from "./bits";
import { Badge, Skeleton } from "./ui";

function Coin({ symbol, compact }: { symbol: string; compact?: boolean }) {
  const [b, q] = pair(symbol).split("/");
  return (
    <div className="flex items-center gap-2.5">
      <div className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-raised text-[8.5px] font-bold tracking-tight text-ink ring-1 ring-line">{b.slice(0, 4)}</div>
      <div className="leading-tight">
        <div className="font-semibold text-ink">{b}{!compact && <span className="font-normal text-faint">/{q}</span>}</div>
      </div>
    </div>
  );
}

export function ActiveSignalsTable({ rows, loading }: { rows: Signal[]; loading?: boolean }) {
  const nav = useNavigate();
  const { data: prices } = usePrices();
  const { flashed } = useLive();
  const now = useNow(15_000);
  if (loading) return <TableSkeleton />;
  return (
    <>
    <ul className="divide-y divide-line/60 sm:hidden">
      {rows.map((s) => {
        const last = prices?.prices?.[s.symbol] ?? s.last_price;
        const upnl = last ? unrealized(s.side, s.entry_price, last) : null;
        const left = (new Date(s.expires_at).getTime() - now) / 1000;
        return (
          <li key={s.id} onClick={() => nav(`/signals/${s.id}`)} className={clsx("cursor-pointer px-4 py-3.5 active:bg-raised", flashed.has(s.id) && "animate-flash")}>
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2"><Coin symbol={s.symbol} /><SideBadge side={s.side} /></div>
              <PnL value={upnl} className="text-sm font-semibold" />
            </div>
            <div className="mt-2.5"><LevelBar entry={s.entry_price} tp={s.take_profit} sl={s.stop_loss} last={last} compact /></div>
            <div className="num mt-1 flex justify-between text-2xs">
              <span className="text-short/90">SL {price(s.stop_loss)}</span>
              <span className="text-muted">entry {price(s.entry_price)}</span>
              <span className="text-long/90">TP {price(s.take_profit)}</span>
            </div>
            <div className="mt-2 flex items-center justify-between text-xs text-muted">
              <StrategyChip code={s.strategy} />
              <span className="num inline-flex items-center gap-1"><Clock3 size={12} />{left > 0 ? duration(left) : "closing"} left</span>
            </div>
          </li>
        );
      })}
    </ul>
    <div className="hidden overflow-x-auto sm:block">
      <table className="w-full min-w-[880px] text-sm">
        <thead>
          <tr className="table-head">
            <th className="px-4 py-2.5 sm:px-5">Market</th>
            <th className="px-3 py-2.5">Strategy</th>
            <th className="px-3 py-2.5 text-right">Entry</th>
            <th className="px-3 py-2.5 text-right">Last</th>
            <th className="w-[22%] px-3 py-2.5">Stop ⟶ Target</th>
            <th className="px-3 py-2.5 text-right">Open P&amp;L</th>
            <th className="px-3 py-2.5 text-right">Time left</th>
            <th className="w-8" />
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => {
            const last = prices?.prices?.[s.symbol] ?? s.last_price;
            const upnl = last ? unrealized(s.side, s.entry_price, last) : null;
            const left = (new Date(s.expires_at).getTime() - now) / 1000;
            return (
              <tr key={s.id} onClick={() => nav(`/signals/${s.id}`)} className={clsx("table-row cursor-pointer", flashed.has(s.id) && "animate-flash")}>
                <td className="px-4 py-3 sm:px-5">
                  <div className="flex items-center gap-3"><Coin symbol={s.symbol} /><SideBadge side={s.side} /></div>
                </td>
                <td className="px-3 py-3"><StrategyChip code={s.strategy} /></td>
                <td className="num px-3 py-3 text-right text-muted">{price(s.entry_price)}</td>
                <td className="num px-3 py-3 text-right">{price(last)}</td>
                <td className="px-3 py-3">
                  <LevelBar entry={s.entry_price} tp={s.take_profit} sl={s.stop_loss} last={last} compact />
                  <div className="num mt-0.5 flex justify-between text-2xs text-faint">
                    <span className="text-short/80">{price(s.stop_loss)}</span>
                    <span className="text-long/80">{price(s.take_profit)}</span>
                  </div>
                </td>
                <td className="px-3 py-3 text-right"><PnL value={upnl} /></td>
                <td className="num px-3 py-3 text-right text-muted">
                  <span className="inline-flex items-center gap-1"><Clock3 size={12} />{left > 0 ? duration(left) : "closing"}</span>
                </td>
                <td className="pr-3 text-faint"><ChevronRight size={16} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
    </>
  );
}

export function HistoryTable({ rows, loading }: { rows: Signal[]; loading?: boolean }) {
  const nav = useNavigate();
  const { flashed } = useLive();
  const { data: meta } = useMeta();
  // the demo banner already says so; badge only rows that differ from the site's own origin
  const siteOrigin = meta?.demo ? "demo" : "live";
  if (loading) return <TableSkeleton />;
  return (
    <>
    <ul className="divide-y divide-line/60 sm:hidden">
      {rows.map((s) => (
        <li key={s.id} onClick={() => nav(`/signals/${s.id}`)} className="flex cursor-pointer items-center gap-3 px-4 py-3 active:bg-raised">
          <div className="w-[72px] shrink-0"><Coin symbol={s.symbol} compact /></div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5"><SideBadge side={s.side} /><OutcomeBadge reason={s.exit_reason} pnl={s.pnl_net_pct} /></div>
            <div className="num mt-1 truncate text-2xs text-faint">{utc(s.entry_at)} · {s.strategy}</div>
          </div>
          <div className="text-right">
            <PnL value={s.status === "CLOSED" ? s.pnl_net_pct : s.unrealized_pct} className="text-sm" />
            <div className="num text-2xs text-faint">{r(s.r_multiple)}</div>
          </div>
        </li>
      ))}
    </ul>
    <div className="hidden overflow-x-auto sm:block">
      <table className="w-full min-w-[900px] text-sm">
        <thead>
          <tr className="table-head">
            <th className="px-4 py-2.5 sm:px-5">Market</th>
            <th className="px-3 py-2.5">Strategy</th>
            <th className="px-3 py-2.5">Opened (UTC)</th>
            <th className="px-3 py-2.5 text-right">Entry</th>
            <th className="px-3 py-2.5 text-right">Exit</th>
            <th className="px-3 py-2.5">Outcome</th>
            <th className="px-3 py-2.5 text-right">Net</th>
            <th className="px-3 py-2.5 text-right">R</th>
            <th className="px-3 py-2.5 text-right">Held</th>
            <th className="w-8" />
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => {
            const held = s.exit_at ? (new Date(s.exit_at).getTime() - new Date(s.entry_at).getTime()) / 1000 : null;
            return (
              <tr key={s.id} onClick={() => nav(`/signals/${s.id}`)} className={clsx("table-row cursor-pointer", flashed.has(s.id) && "animate-flash")}>
                <td className="px-4 py-3 sm:px-5">
                  <div className="flex items-center gap-3"><Coin symbol={s.symbol} /><SideBadge side={s.side} />
                    {s.origin !== siteOrigin && <Badge tone="warn" title="not produced in real time">{s.origin}</Badge>}
                  </div>
                </td>
                <td className="px-3 py-3"><StrategyChip code={s.strategy} /></td>
                <td className="num px-3 py-3 text-muted">{utc(s.entry_at)}</td>
                <td className="num px-3 py-3 text-right text-muted">{price(s.entry_price)}</td>
                <td className="num px-3 py-3 text-right">{s.status === "CLOSED" ? price(s.exit_price) : "—"}</td>
                <td className="px-3 py-3"><OutcomeBadge reason={s.exit_reason} pnl={s.pnl_net_pct} /></td>
                <td className="px-3 py-3 text-right"><PnL value={s.status === "CLOSED" ? s.pnl_net_pct : s.unrealized_pct} /></td>
                <td className={clsx("num px-3 py-3 text-right", (s.r_multiple ?? 0) >= 0 ? "text-muted" : "text-short")}>{r(s.r_multiple)}</td>
                <td className="num px-3 py-3 text-right text-muted">{held !== null ? duration(held) : "—"}</td>
                <td className="pr-3 text-faint"><ChevronRight size={16} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
    </>
  );
}

function TableSkeleton() {
  return (
    <div className="space-y-2 p-5">
      {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}
    </div>
  );
}
