import { useQuery } from "@tanstack/react-query";
import { api, type SignalFilters } from "./api";

export const useMeta = () => useQuery({ queryKey: ["meta"], queryFn: api.meta, refetchInterval: 30_000 });

export const usePrices = () => useQuery({ queryKey: ["prices"], queryFn: api.prices, refetchInterval: 60_000 });

export const useRegime = () => useQuery({ queryKey: ["regime"], queryFn: api.regime, refetchInterval: 120_000 });

export const useSignals = (f: SignalFilters) =>
  useQuery({ queryKey: ["signals", f], queryFn: () => api.signals(f), placeholderData: (prev) => prev });

export const useStats = (q: { strategy?: string; days?: number | null; origin?: string }) =>
  useQuery({ queryKey: ["stats", q], queryFn: () => api.stats(q), placeholderData: (prev) => prev });

export const useEquity = (q: { strategy?: string; risk?: number; days?: number | null; origin?: string }) =>
  useQuery({ queryKey: ["equity", q], queryFn: () => api.equity(q), placeholderData: (prev) => prev });

export const useMonthly = (q: { strategy?: string; origin?: string }) =>
  useQuery({ queryKey: ["monthly", q], queryFn: () => api.monthly(q) });

/** Latest known price: the 15 s price feed, else the tracker's last price on the signal. */
export function useLivePrice(symbol: string, fallback: number | null): number | null {
  const { data } = usePrices();
  return data?.prices?.[symbol] ?? fallback;
}
