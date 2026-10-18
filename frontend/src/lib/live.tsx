import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { Prices, RegimeItem, Signal } from "./types";

type Status = "connecting" | "open" | "closed";

interface Toast {
  id: number;
  signal: Signal;
  kind: "new" | "closed";
}

interface LiveState {
  status: Status;
  toasts: Toast[];
  dismiss: (id: number) => void;
  flashed: Set<number>;
}

const LiveContext = createContext<LiveState>({ status: "connecting", toasts: [], dismiss: () => {}, flashed: new Set() });

/** One EventSource for the whole app: pushes signal changes, prices, regime and heartbeat into
 *  the React Query cache so every page updates in place. */
export function LiveProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [status, setStatus] = useState<Status>("connecting");
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [flashed, setFlashed] = useState<Set<number>>(new Set());
  const seen = useRef(new Map<number, string>());
  const invalidateTimer = useRef<number | null>(null);

  useEffect(() => {
    const es = new EventSource("/api/stream");
    es.onopen = () => setStatus("open");
    es.onerror = () => setStatus(es.readyState === EventSource.CLOSED ? "closed" : "connecting");

    const scheduleInvalidate = () => {
      if (invalidateTimer.current) return;
      invalidateTimer.current = window.setTimeout(() => {
        invalidateTimer.current = null;
        qc.invalidateQueries({ queryKey: ["signals"] });
        qc.invalidateQueries({ queryKey: ["stats"] });
        qc.invalidateQueries({ queryKey: ["equity"] });
        qc.invalidateQueries({ queryKey: ["monthly"] });
      }, 800);
    };

    es.addEventListener("signal", (e) => {
      const s: Signal = JSON.parse((e as MessageEvent).data);
      const prev = seen.current.get(s.id);
      seen.current.set(s.id, s.status);
      qc.setQueryData(["signal", String(s.id)], s);
      scheduleInvalidate();
      const fresh = Date.now() - new Date(s.created_at).getTime() < 10 * 60 * 1000;
      let kind: Toast["kind"] | null = null;
      if (!prev && s.status === "ACTIVE" && fresh) kind = "new";
      else if (prev === "ACTIVE" && s.status === "CLOSED") kind = "closed";
      if (kind) {
        const id = Date.now() + s.id;
        setToasts((t) => [...t.slice(-3), { id, signal: s, kind: kind! }]);
        window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 9000);
      }
      setFlashed((f) => new Set(f).add(s.id));
      window.setTimeout(() => setFlashed((f) => {
        const n = new Set(f);
        n.delete(s.id);
        return n;
      }), 1800);
    });
    es.addEventListener("prices", (e) => qc.setQueryData<Prices>(["prices"], JSON.parse((e as MessageEvent).data)));
    es.addEventListener("regime", (e) =>
      qc.setQueryData<{ items: Record<string, RegimeItem> }>(["regime"], { items: JSON.parse((e as MessageEvent).data) }),
    );
    es.addEventListener("heartbeat", () => qc.invalidateQueries({ queryKey: ["meta"] }));
    return () => {
      es.close();
      if (invalidateTimer.current) window.clearTimeout(invalidateTimer.current);
    };
  }, [qc]);

  const value = useMemo<LiveState>(
    () => ({ status, toasts, flashed, dismiss: (id) => setToasts((t) => t.filter((x) => x.id !== id)) }),
    [status, toasts, flashed],
  );
  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

export const useLive = () => useContext(LiveContext);
