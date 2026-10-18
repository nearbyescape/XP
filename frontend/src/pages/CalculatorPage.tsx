import { useMemo, useState } from "react";
import { useMeta, useSignals } from "@/lib/queries";
import { pair } from "@/lib/format";
import { Card, CardHeader, Select } from "@/components/ui";
import { PositionCalculator } from "@/components/Calculator";

export default function CalculatorPage() {
  const { data: meta } = useMeta();
  const { data: active } = useSignals({ status: "active", limit: 100 });
  const [pick, setPick] = useState("");
  const chosen = useMemo(() => active?.items.find((s) => String(s.id) === pick), [active, pick]);
  return (
    <div className="space-y-6">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight">Position size calculator</h1>
        <p className="mt-1 text-sm text-muted">
          Signals have wide stops and small targets, so position size must come from the stop. Risking the same % of equity on every signal keeps one
          stop-out from erasing many wins.
        </p>
      </div>
      <Card>
        <CardHeader
          title="Size a trade"
          actions={
            <Select label="Load an active signal" value={pick} onChange={setPick}>
              <option value="">Load an active signal…</option>
              {active?.items.map((s) => <option key={s.id} value={s.id}>{s.side} {pair(s.symbol)} · {s.strategy} · #{s.id}</option>)}
            </Select>
          }
        />
        <div className="card-pad">
          <PositionCalculator key={pick} entry={chosen?.entry_price} stop={chosen?.stop_loss} target={chosen?.take_profit} defaultRisk={meta?.default_risk_pct} />
        </div>
      </Card>
    </div>
  );
}
