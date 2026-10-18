import type { Signal } from "./types";

// Number and time formatting. Times are shown in the publishing session's timezone (e.g. IST), set from /api/meta.

export function price(x: number | null | undefined): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  const a = Math.abs(x);
  const digits = a >= 100 ? 2 : a >= 1 ? 4 : a >= 0.01 ? 5 : 8;
  return x.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Shorter price for dense grids (no wrapping on 5-digit BTC prices). */
export function priceShort(x: number | null | undefined): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  const a = Math.abs(x);
  const digits = a >= 1000 ? 0 : a >= 100 ? 1 : a >= 1 ? 3 : 4;
  return x.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Account currency amounts (USDT): always 2 decimals. */
export function money(x: number | null | undefined): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return x.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** A price as plain text for an <input> (display precision, no thousands separators). */
export function priceInput(x: number | null | undefined): string {
  return x === null || x === undefined ? "" : price(x).replace(/,/g, "");
}

export function pct(x: number | null | undefined, digits = 2, signed = true): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  const s = x.toFixed(digits);
  return `${signed && x > 0 ? "+" : ""}${s.replace("-", "−")}%`;
}

export function num(x: number | null | undefined, digits = 2): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return x.toFixed(digits).replace("-", "−");
}

export function r(x: number | null | undefined, digits = 2): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return `${x > 0 ? "+" : ""}${x.toFixed(digits).replace("-", "−")}R`;
}

export function pair(symbol: string): string {
  return symbol.endsWith("USDT") ? `${symbol.slice(0, -4)}/USDT` : symbol;
}

export function base(symbol: string): string {
  return symbol.endsWith("USDT") ? symbol.slice(0, -4) : symbol;
}

const pad = (n: number) => String(n).padStart(2, "0");
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

let TZ = "UTC";
let TZ_ABBR = "UTC";
let FMT = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, day: "2-digit", month: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

/** Display timezone for every time on the site (the session timezone from /api/meta). */
export function setTimeZone(tz: string, abbr: string) {
  if (tz === TZ) return;
  TZ = tz;
  TZ_ABBR = abbr;
  FMT = new Intl.DateTimeFormat("en-GB", { timeZone: tz, day: "2-digit", month: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
}

export const tz = () => TZ_ABBR;

function parts(ts: string | number | Date) {
  const p = Object.fromEntries(FMT.formatToParts(new Date(ts)).map((x) => [x.type, x.value]));
  return { day: p.day, month: MONTHS[Number(p.month) - 1], year: p.year, hour: p.hour, minute: p.minute };
}

/** "18 Oct 09:30" (or "18 Oct 2026 09:30") in the display timezone. */
export function stamp(ts: string | number | Date | null | undefined, withYear = false): string {
  if (!ts) return "—";
  const p = parts(ts);
  return `${p.day} ${p.month}${withYear ? ` ${p.year}` : ""} ${p.hour}:${p.minute}`;
}

export function stampDate(ts: string | null | undefined): string {
  if (!ts) return "—";
  const p = parts(ts);
  return `${p.day} ${p.month} ${p.year}`;
}

export function duration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${pad(m)}m`;
  return `${m}m`;
}

export function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
}

export function ago(ts: string | null | undefined, now: number = Date.now()): string {
  if (!ts) return "—";
  const sec = (now - new Date(ts).getTime()) / 1000;
  if (sec < 45) return "just now";
  return `${duration(sec)} ago`;
}

export function monthLabel(m: string): string {
  const [y, mo] = m.split("-").map(Number);
  return `${MONTHS[mo - 1]} ${y}`;
}

export function unrealized(side: "LONG" | "SHORT", entry: number, last: number): number {
  return (side === "LONG" ? last / entry - 1 : 1 - last / entry) * 100;
}

/** Return of the whole position in percent, before costs: targets already closed plus the rest at `last`. */
export function positionReturn(s: Pick<Signal, "side" | "entry_price" | "targets">, last: number): number {
  const dir = s.side === "LONG" ? 1 : -1;
  let done = 0;
  let closed = 0;
  for (const t of s.targets) {
    if (t.fill_price === null) continue;
    done += (t.size_pct / 100) * dir * (t.fill_price / s.entry_price - 1);
    closed += t.size_pct / 100;
  }
  return (done + (1 - closed) * dir * (last / s.entry_price - 1)) * 100;
}
