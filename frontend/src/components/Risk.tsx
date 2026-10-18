import clsx from "clsx";
import { ShieldCheck, ShieldAlert } from "lucide-react";
import { num } from "@/lib/format";
import type { Meta, Signal } from "@/lib/types";

/** Open signals still before TP1: their stop can still lose. After TP1 the stop sits at entry. */
export function exposureOf(rows: Signal[]) {
  const risky = rows.filter((s) => s.status === "ACTIVE" && (!s.targets_hit || !s.breakeven));
  const long = risky.filter((s) => s.side === "LONG").length;
  return { open: rows.filter((s) => s.status === "ACTIVE").length, atRisk: risky.length, long, short: risky.length - long };
}

/** "Open risk 2.0% of 5% · 4 before TP1 · 3 long / 1 short", with a bar toward the member limit. */
export function OpenRiskMeter({ rows, risk }: { rows: Signal[]; risk: Meta["risk"] }) {
  const e = exposureOf(rows);
  const total = e.atRisk * risk.risk_pct;
  const over = total > risk.max_open_risk_pct;
  const fill = Math.min(1, total / risk.max_open_risk_pct);
  const Icon = over ? ShieldAlert : ShieldCheck;
  return (
    <div
      className={clsx("flex items-center gap-2.5 rounded-lg border px-2.5 py-1.5", over ? "border-warn/40 bg-warn/10" : "border-line bg-raised/60")}
      title={`If every signal still before TP1 hit its stop together, at ${risk.risk_pct}% risk each. Member rule: keep the total under ${risk.max_open_risk_pct}%.`}
    >
      <Icon size={15} className={over ? "text-warn" : "text-long"} />
      <div className="min-w-0">
        <div className="flex items-baseline gap-1.5 text-xs">
          <span className="text-muted">Open risk</span>
          <span className={clsx("num font-semibold", over ? "text-warn" : "text-ink")}>{num(total, 1)}%</span>
          <span className="num text-faint">of {num(risk.max_open_risk_pct, 0)}%</span>
        </div>
        <div className="mt-1 h-1 w-28 overflow-hidden rounded-full bg-line">
          <div className={clsx("h-full rounded-full", over ? "bg-warn" : fill > 0.6 ? "bg-warn/70" : "bg-long")} style={{ width: `${fill * 100}%` }} />
        </div>
      </div>
      <div className="num hidden text-2xs leading-tight text-muted sm:block">
        {e.atRisk ? <>{e.atRisk} before TP1<br />{e.long} long / {e.short} short</> : <>none before TP1<br />stops at entry</>}
      </div>
    </div>
  );
}

const plain = (x: number) => String(+x.toFixed(2)); // 0.5 → "0.5", 0.25 → "0.25", 5 → "5"

/** The member rules, as pinned in the Telegram channel. */
export function MemberRules({ meta }: { meta?: Meta }) {
  const r = meta?.risk ?? { risk_pct: 0.5, max_open_risk_pct: 5, note_signals: 10 };
  const most = Math.round(r.max_open_risk_pct / r.risk_pct);
  const rules: [string, string][] = [
    ["Enter inside the window", `Enter at market within ${meta?.session.entry_window_minutes ?? 15} minutes of the 4H close. After that, skip the signal.`],
    ["Stop on the exchange at once", "A stop-market, reduce-only order the moment you enter, never a mental stop. TP1, TP2 and TP3 rest as limit orders for 50%, 30% and 20%."],
    [`Risk ${plain(r.risk_pct)}% per signal`, `${plain(r.risk_pct / 2)}% while you are new. The calculator sizes the trade; with isolated margin no extra leverage is needed.`],
    [`Keep open risk under ${plain(r.max_open_risk_pct)}%`, `Signals still before TP1 count: at ${plain(r.risk_pct)}% each that is ${most}. The meter on the active signals shows the total now.`],
    ["Stop to entry after TP1", "The rest of the trade then runs risk-free. Close anything still open at the expiry."],
  ];
  return (
    <ol className="space-y-2 p-4 text-sm text-muted sm:p-5">
      {rules.map(([t, d], i) => (
        <li key={t} className="flex gap-3 rounded-lg border border-line/70 bg-raised/40 p-3">
          <span className="num grid h-6 w-6 shrink-0 place-items-center rounded-md bg-accent/15 text-xs font-semibold text-accent">{i + 1}</span>
          <span><span className="font-medium text-ink">{t}.</span> {d}</span>
        </li>
      ))}
    </ol>
  );
}
