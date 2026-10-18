import type { AdminOverview, Candle, Equity, Meta, MonthRow, Page, Prices, RegimeItem, Signal, Stats } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

function qs(params?: Query): string {
  if (!params) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

async function request<T>(path: string, init?: RequestInit & { query?: Query }): Promise<T> {
  const res = await fetch(`/api${path}${qs(init?.query)}`, {
    credentials: "same-origin",
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      // CSRF defence for admin mutations (checked server-side)
      "X-Requested-With": "SignalDesk",
      ...init?.headers,
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export interface SignalFilters {
  status?: "active" | "closed" | "all";
  strategy?: string;
  symbol?: string;
  side?: "long" | "short";
  outcome?: "TP" | "SL" | "BE" | "TIME";
  origin?: string;
  limit?: number;
  offset?: number;
}

export const api = {
  meta: () => request<Meta>("/meta"),
  signals: (f: SignalFilters) => request<Page<Signal>>("/signals", { query: { ...f } }),
  signal: (id: number | string) => request<Signal>(`/signals/${id}`),
  signalsCsvUrl: (f: SignalFilters) => `/api/signals.csv${qs({ ...f, limit: undefined, offset: undefined })}`,
  stats: (q: { strategy?: string; days?: number | null; origin?: string }) =>
    request<Stats>("/stats", { query: q }),
  equity: (q: { strategy?: string; risk?: number; days?: number | null; origin?: string }) =>
    request<Equity>("/stats/equity", { query: q }),
  monthly: (q: { strategy?: string; origin?: string }) => request<MonthRow[]>("/stats/monthly", { query: q }),
  regime: () => request<{ items: Record<string, RegimeItem> }>("/regime"),
  prices: () => request<Prices>("/prices"),
  candles: (symbol: string, limit = 300, end?: string) => request<Candle[]>("/candles", { query: { symbol, limit, end } }),

  admin: {
    login: (username: string, password: string) =>
      request<void>("/admin/login", { method: "POST", body: JSON.stringify({ username, password }) }),
    logout: () => request<void>("/admin/logout", { method: "POST" }),
    me: () => request<{ username: string }>("/admin/me"),
    overview: () => request<AdminOverview>("/admin/overview"),
    setStrategy: (code: string, body: { mode?: string; resume?: boolean }) =>
      request<{ code: string; mode: string; auto_paused: boolean }>(`/admin/strategies/${code}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    telegramTest: (chat_id?: string) =>
      request<{ queued: boolean; chat_id: string }>("/admin/telegram/test", {
        method: "POST",
        body: JSON.stringify({ chat_id: chat_id || null }),
      }),
    telegramRules: () => request<{ queued: boolean; chat_id: string }>("/admin/telegram/rules", { method: "POST" }),
    setPublishing: (paused: boolean) =>
      request<{ paused: boolean; by?: string; at?: string; changed: boolean }>("/admin/publishing", {
        method: "PUT",
        body: JSON.stringify({ paused }),
      }),
    shadowStats: () => request<Record<string, Stats["kpis"]>>("/admin/stats/shadow"),
  },
};
