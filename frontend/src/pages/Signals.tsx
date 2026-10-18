import { ChevronLeft, ChevronRight, Download, Inbox } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { api, type SignalFilters } from "@/lib/api";
import { useMeta, useSignals } from "@/lib/queries";
import { base } from "@/lib/format";
import { Card, CardHeader, Empty, Segmented, Select } from "@/components/ui";
import { ActiveSignalsTable, HistoryTable } from "@/components/SignalsTable";

const PAGE = 25;

export default function Signals() {
  const { data: meta } = useMeta();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as "active" | "history") || "active";
  const page = Number(params.get("page") || 0);
  const set = (k: string, v: string | null) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v);
    else p.delete(k);
    if (k !== "page") p.delete("page");
    setParams(p, { replace: true });
  };
  const filters: SignalFilters = {
    status: tab === "active" ? "active" : "closed",
    strategy: params.get("strategy") || undefined,
    symbol: params.get("symbol") || undefined,
    side: (params.get("side") as "long" | "short") || undefined,
    outcome: tab === "history" ? ((params.get("outcome") as "TP" | "SL" | "BE" | "TIME") || undefined) : undefined,
    origin: params.get("origin") || undefined,
    limit: tab === "active" ? 200 : PAGE,
    offset: tab === "active" ? 0 : page * PAGE,
  };
  const { data, isLoading, isFetching } = useSignals(filters);
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE)) : 1;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Signals</h1>
        <p className="mt-1 text-sm text-muted">Every published signal with its fixed levels and final result. Nothing is ever removed from the ledger.</p>
      </div>
      <Card>
        <CardHeader
          title={
            <Segmented value={tab} onChange={(v) => set("tab", v === "active" ? null : v)}
              options={[{ value: "active", label: "Active" }, { value: "history", label: "History" }]} />
          }
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <Select label="Strategy" value={params.get("strategy") ?? ""} onChange={(v) => set("strategy", v || null)}>
                <option value="">All strategies</option>
                {meta?.strategies.map((s) => <option key={s.code} value={s.code}>{s.letter} · {s.name}</option>)}
              </Select>
              <Select label="Market" value={params.get("symbol") ?? ""} onChange={(v) => set("symbol", v || null)}>
                <option value="">All markets</option>
                {meta?.universe.map((s) => <option key={s} value={s}>{base(s)}</option>)}
              </Select>
              <Select label="Side" value={params.get("side") ?? ""} onChange={(v) => set("side", v || null)}>
                <option value="">Both sides</option>
                <option value="long">Long</option>
                <option value="short">Short</option>
              </Select>
              {tab === "history" && (
                <>
                  <Select label="Outcome" value={params.get("outcome") ?? ""} onChange={(v) => set("outcome", v || null)}>
                    <option value="">All outcomes</option>
                    <option value="TP">All targets</option>
                    <option value="BE">TP1+ then entry</option>
                    <option value="SL">Stop</option>
                    <option value="TIME">Time exit</option>
                  </Select>
                  <Select label="Origin" value={params.get("origin") ?? ""} onChange={(v) => set("origin", v || null)}>
                    <option value="">Real-time</option>
                    <option value="all">Incl. backfilled</option>
                  </Select>
                  <a className="btn" href={api.signalsCsvUrl(filters)}><Download size={14} /> CSV</a>
                </>
              )}
            </div>
          }
        />
        {!isLoading && !data?.items.length ? (
          <Empty icon={<Inbox size={28} />} title={tab === "active" ? "No open signals" : "No signals match these filters"}>
            {tab === "active" ? "New signals are evaluated at every 4H close (00/04/08/12/16/20 UTC)." : "Try clearing a filter."}
          </Empty>
        ) : tab === "active" ? (
          <ActiveSignalsTable rows={data?.items ?? []} loading={isLoading} />
        ) : (
          <HistoryTable rows={data?.items ?? []} loading={isLoading} />
        )}
        {tab === "history" && data && data.total > PAGE && (
          <div className="flex items-center justify-between border-t border-line px-4 py-3 text-sm text-muted sm:px-5">
            <span className="num">{(page * PAGE + 1).toLocaleString()}–{Math.min(data.total, (page + 1) * PAGE).toLocaleString()} of {data.total.toLocaleString()}{isFetching ? " · loading…" : ""}</span>
            <div className="flex gap-2">
              <button className="btn px-2" disabled={page === 0} onClick={() => set("page", String(page - 1))} aria-label="Previous page"><ChevronLeft size={15} /></button>
              <button className="btn px-2" disabled={page + 1 >= pages} onClick={() => set("page", String(page + 1))} aria-label="Next page"><ChevronRight size={15} /></button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
