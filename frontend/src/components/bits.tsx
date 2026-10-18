import clsx from "clsx";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { useEffect, useState } from "react";
import type { ExitReason, Side } from "@/lib/types";
import { Badge } from "./ui";
import { clock, pct } from "@/lib/format";

export const STRATEGY_STYLE: Record<string, { chip: string; dot: string; letter: string; short: string }> = {
  "RGP-4H": { chip: "border-sky-400/30 bg-sky-400/10 text-sky-400", dot: "bg-sky-400", letter: "A", short: "Pullback" },
  "RSR-4H": { chip: "border-violet-400/30 bg-violet-400/10 text-violet-400", dot: "bg-violet-400", letter: "B", short: "Sweep" },
  "MLR-4H": { chip: "border-fuchsia-400/30 bg-fuchsia-400/10 text-fuchsia-400", dot: "bg-fuchsia-400", letter: "C", short: "ML-Ranked" },
};

export function StrategyChip({ code, full }: { code: string; full?: boolean }) {
  const s = STRATEGY_STYLE[code] ?? { chip: "border-line text-muted", letter: "?", short: code, dot: "" };
  return (
    <span className={clsx("inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-2xs font-semibold", s.chip)} title={code}>
      <span className="num">{s.letter}</span>
      <span className="font-medium opacity-90">{full ? code : s.short}</span>
    </span>
  );
}

export function SideBadge({ side }: { side: Side }) {
  return side === "LONG" ? (
    <Badge tone="long"><ArrowUpRight size={12} strokeWidth={2.5} />Long</Badge>
  ) : (
    <Badge tone="short"><ArrowDownRight size={12} strokeWidth={2.5} />Short</Badge>
  );
}

export function OutcomeBadge({ reason, pnl }: { reason: ExitReason | null; pnl?: number | null }) {
  if (!reason) return <Badge tone="accent">Active</Badge>;
  const label = { TP: "Target", SL: "Stop", TIME: "Time" }[reason];
  const tone = reason === "TP" ? "long" : reason === "SL" ? "short" : (pnl ?? 0) > 0 ? "long" : "warn";
  return <Badge tone={tone}>{label}</Badge>;
}

export function Trend({ value, className }: { value: number; className?: string }) {
  if (value === 1) return <span className={clsx("inline-flex items-center text-long", className)} title="Up-trend"><ArrowUpRight size={14} strokeWidth={2.5} /></span>;
  if (value === -1) return <span className={clsx("inline-flex items-center text-short", className)} title="Down-trend"><ArrowDownRight size={14} strokeWidth={2.5} /></span>;
  return <span className={clsx("inline-flex items-center text-faint", className)} title="Neutral"><Minus size={14} strokeWidth={2.5} /></span>;
}

export function PnL({ value, className, suffix = "" }: { value: number | null | undefined; className?: string; suffix?: string }) {
  if (value === null || value === undefined) return <span className={clsx("num text-faint", className)}>—</span>;
  return (
    <span className={clsx("num", value > 0 ? "text-long" : value < 0 ? "text-short" : "text-muted", className)}>
      {pct(value)}
      {suffix}
    </span>
  );
}

/** Position of the live price between the stop (left) and the target (right). */
export function LevelBar({ entry, tp, sl, last, compact }: { entry: number; tp: number; sl: number; last: number | null; compact?: boolean }) {
  const span = tp - sl;
  const clamp = (x: number) => Math.max(0, Math.min(1, x));
  const entryPos = clamp((entry - sl) / span);
  const pos = last === null ? null : clamp((last - sl) / span);
  return (
    <div className={clsx("relative w-full", compact ? "h-4" : "h-6")} aria-label="price between stop and target">
      <div className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 overflow-hidden rounded-full bg-raised ring-1 ring-line">
        <div className="absolute inset-y-0 left-0 bg-gradient-to-r from-short/70 to-short/15" style={{ width: `${entryPos * 100}%` }} />
        <div className="absolute inset-y-0 bg-gradient-to-r from-long/20 to-long/80" style={{ left: `${entryPos * 100}%`, right: 0 }} />
      </div>
      <div className="absolute top-1/2 h-3 w-px -translate-y-1/2 bg-ink/60" style={{ left: `${entryPos * 100}%` }} title="entry" />
      {pos !== null && (
        <div
          className={clsx("absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface shadow", pos >= entryPos ? "bg-long" : "bg-short")}
          style={{ left: `${pos * 100}%` }}
          title="last price"
        />
      )}
    </div>
  );
}

export function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

/** Countdown to the next 4h close, corrected for the browser/server clock offset. */
export function Countdown({ target, serverTime }: { target: string; serverTime: string }) {
  const now = useNow();
  const [offset] = useState(() => new Date(serverTime).getTime() - Date.now());
  const left = (new Date(target).getTime() - (now + offset)) / 1000;
  return <span className="num">{left > 0 ? clock(left) : "evaluating…"}</span>;
}

export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <rect width="32" height="32" rx="8" className="fill-raised stroke-line" strokeWidth="1" />
      <path d="M5 19h5l3-9 5 14 3-8h6" fill="none" className="stroke-accent" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="27" cy="16" r="2.4" className="fill-long" />
    </svg>
  );
}
