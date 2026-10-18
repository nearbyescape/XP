import { useEffect, useMemo, useState } from "react";
import { money, num, price, priceInput } from "@/lib/format";
import type { Target } from "@/lib/types";

function useStored(key: string, initial: string) {
  const [v, setV] = useState(() => {
    try {
      return localStorage.getItem(key) ?? initial;
    } catch {
      return initial;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(key, v);
    } catch {
      /* ignore */
    }
  }, [key, v]);
  return [v, setV] as const;
}

/** Risk-based position sizing: the stop defines the size, never the other way round. */
export function PositionCalculator({ entry, stop, target, targets, defaultRisk = 0.5, maxOpenRisk = 5, compact }: {
  entry?: number;
  stop?: number;
  target?: number;
  targets?: Target[]; // TP1/TP2/TP3 of a signal: gains are shown per target
  defaultRisk?: number;
  maxOpenRisk?: number; // member rule: total risk across signals still before TP1, % of the account
  compact?: boolean;
}) {
  const [account, setAccount] = useStored("sd-account", "10000");
  const [risk, setRisk] = useStored("sd-risk", String(defaultRisk));
  const [held, setHeld] = useStored("sd-held", "0");
  const [e, setE] = useState(priceInput(entry));
  const [s, setS] = useState(priceInput(stop));
  const [t, setT] = useState(priceInput(target));
  useEffect(() => {
    if (entry) setE(priceInput(entry));
    if (stop) setS(priceInput(stop));
    if (target) setT(priceInput(target));
  }, [entry, stop, target]);

  const out = useMemo(() => {
    const A = parseFloat(account), R = parseFloat(risk) / 100, E = parseFloat(e), S = parseFloat(s), T = parseFloat(t);
    if (!(A > 0 && R > 0 && E > 0 && S > 0) || E === S) return null;
    const stopDist = Math.abs(E - S) / E;
    const riskAmt = A * R;
    const notional = riskAmt / stopDist;
    const qty = notional / E;
    const reward = T > 0 ? qty * Math.abs(T - E) : null;
    const ladder = targets?.map((x) => ({ n: x.n, size: x.size_pct / 100, qty: (qty * x.size_pct) / 100, gain: (qty * x.size_pct / 100) * Math.abs(x.price - E), price: x.price }));
    // this trade plus the signals already held that are still before TP1, each at the same risk
    const openRisk = (Math.max(0, Math.floor(parseFloat(held) || 0)) + 1) * R * 100;
    return { stopDist, riskAmt, notional, qty, leverage: notional / A, reward, ladder, openRisk };
  }, [account, risk, held, e, s, t, targets]);
  const qtyFmt = (q: number) => num(q, q >= 100 ? 2 : q >= 1 ? 4 : 6);

  const field = (label: string, value: string, set: (v: string) => void, suffix?: string, readOnly?: boolean) => (
    <label className="block">
      <span className="label">{label}</span>
      <div className="relative mt-1.5">
        <input className="input num pr-14" inputMode="decimal" value={value} onChange={(ev) => set(ev.target.value)} readOnly={readOnly} />
        {suffix && <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-faint">{suffix}</span>}
      </div>
    </label>
  );

  return (
    <div className={compact ? "space-y-4" : "grid gap-6 lg:grid-cols-2"}>
      <div className="grid grid-cols-2 content-start gap-3">
        {field("Account size", account, setAccount, "USDT")}
        {field("Risk per signal", risk, setRisk, "%")}
        {field("Entry", e, setE)}
        {field("Stop-loss", s, setS)}
        {!compact && !targets && field("Take-profit (optional)", t, setT)}
        <div className="col-span-2">{field("Signals you already hold before TP1", held, setHeld, "open")}</div>
      </div>
      <div className="rounded-xl border border-line bg-raised/60 p-4">
        {out ? (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
            <dt className="text-muted">Position size</dt><dd className="num text-right text-lg font-semibold">{money(out.notional)} <span className="text-xs text-faint">USDT</span></dd>
            <dt className="text-muted">Quantity</dt><dd className="num text-right">{qtyFmt(out.qty)}</dd>
            <dt className="text-muted">Loss if stopped{out.ladder ? " before TP1" : ""}</dt><dd className="num text-right text-short">−{money(out.riskAmt)}</dd>
            {out.ladder ? (
              <>
                {out.ladder.map((x) => (
                  <div key={x.n} className="contents">
                    <dt className="text-muted">TP{x.n} <span className="text-faint">· sell {qtyFmt(x.qty)} at {price(x.price)}</span></dt>
                    <dd className="num text-right text-long">+{money(x.gain)}</dd>
                  </div>
                ))}
                <dt className="text-muted">Gain if every target hits</dt><dd className="num text-right font-semibold text-long">+{money(out.ladder.reduce((a, x) => a + x.gain, 0))}</dd>
              </>
            ) : out.reward !== null && (<><dt className="text-muted">Gain at target</dt><dd className="num text-right text-long">+{money(out.reward)}</dd></>)}
            <dt className="text-muted">Stop distance</dt><dd className="num text-right">{num(out.stopDist * 100)}%</dd>
            <dt className="text-muted">Exposure</dt>
            <dd className={`num text-right ${out.leverage > 1 ? "text-warn" : ""}`}>{num(out.leverage, 2)}× account</dd>
            <dt className="text-muted">Open risk with this trade</dt>
            <dd className={`num text-right ${out.openRisk > maxOpenRisk ? "font-semibold text-warn" : ""}`}>{num(out.openRisk, 1)}% <span className="text-xs text-faint">of {num(maxOpenRisk, 0)}%</span></dd>
          </dl>
        ) : (
          <p className="text-sm text-muted">Enter account size, risk, entry and stop to size the trade.</p>
        )}
        {out?.ladder && <p className="mt-3 text-xs text-muted">After TP1, move the stop to entry: the rest of the trade can no longer lose.</p>}
        {out && out.openRisk > maxOpenRisk && (
          <p className="mt-3 text-xs text-warn">
            Above the {num(maxOpenRisk, 0)}% open-risk rule: skip this signal, or halve the risk until earlier signals reach TP1.
          </p>
        )}
        {out && out.leverage > 1 && (
          <p className="mt-3 text-xs text-warn">Exposure above 1× needs leverage. The validated strategies assume 1× notional — lower the risk instead.</p>
        )}
      </div>
    </div>
  );
}
