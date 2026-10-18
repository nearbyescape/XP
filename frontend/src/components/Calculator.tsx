import { useEffect, useMemo, useState } from "react";
import { money, num, priceInput } from "@/lib/format";

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
export function PositionCalculator({ entry, stop, target, defaultRisk = 0.5, compact }: {
  entry?: number;
  stop?: number;
  target?: number;
  defaultRisk?: number;
  compact?: boolean;
}) {
  const [account, setAccount] = useStored("sd-account", "10000");
  const [risk, setRisk] = useStored("sd-risk", String(defaultRisk));
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
    return { stopDist, riskAmt, notional, qty, leverage: notional / A, reward };
  }, [account, risk, e, s, t]);

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
      <div className="grid grid-cols-2 gap-3">
        {field("Account size", account, setAccount, "USDT")}
        {field("Risk per signal", risk, setRisk, "%")}
        {field("Entry", e, setE)}
        {field("Stop-loss", s, setS)}
        {!compact && field("Take-profit (optional)", t, setT)}
      </div>
      <div className="rounded-xl border border-line bg-raised/60 p-4">
        {out ? (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
            <dt className="text-muted">Position size</dt><dd className="num text-right text-lg font-semibold">{money(out.notional)} <span className="text-xs text-faint">USDT</span></dd>
            <dt className="text-muted">Quantity</dt><dd className="num text-right">{num(out.qty, out.qty >= 100 ? 2 : out.qty >= 1 ? 4 : 6)}</dd>
            <dt className="text-muted">Loss if stopped</dt><dd className="num text-right text-short">−{money(out.riskAmt)}</dd>
            {out.reward !== null && (<><dt className="text-muted">Gain at target</dt><dd className="num text-right text-long">+{money(out.reward)}</dd></>)}
            <dt className="text-muted">Stop distance</dt><dd className="num text-right">{num(out.stopDist * 100)}%</dd>
            <dt className="text-muted">Exposure</dt>
            <dd className={`num text-right ${out.leverage > 1 ? "text-warn" : ""}`}>{num(out.leverage, 2)}× account</dd>
          </dl>
        ) : (
          <p className="text-sm text-muted">Enter account size, risk, entry and stop to size the trade.</p>
        )}
        {out && out.leverage > 1 && (
          <p className="mt-3 text-xs text-warn">Exposure above 1× needs leverage. The validated strategies assume 1× notional — lower the risk instead.</p>
        )}
      </div>
    </div>
  );
}
