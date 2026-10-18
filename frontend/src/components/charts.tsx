import { useEffect, useRef } from "react";
import {
  AreaSeries,
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  LineStyle,
  type IChartApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import type { Candle, Equity, Signal } from "@/lib/types";

function cssColor(name: string, alpha = 1): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
  const [r, g, b] = v.split(/\s+/);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function baseOptions(el: HTMLElement) {
  return {
    width: el.clientWidth,
    height: el.clientHeight,
    layout: {
      background: { type: ColorType.Solid, color: "transparent" },
      textColor: cssColor("muted"),
      fontFamily: "'JetBrains Mono Variable', ui-monospace, monospace",
      fontSize: 11,
      attributionLogo: false,
    },
    grid: { vertLines: { color: cssColor("line", 0.45) }, horzLines: { color: cssColor("line", 0.45) } },
    rightPriceScale: { borderColor: cssColor("line") },
    timeScale: { borderColor: cssColor("line"), timeVisible: true, secondsVisible: false },
    crosshair: { horzLine: { labelBackgroundColor: cssColor("raised") }, vertLine: { labelBackgroundColor: cssColor("raised") } },
    localization: {
      locale: "en-US", // never derive from navigator.language (can be an invalid BCP 47 tag)
      timeFormatter: (t: Time) => new Date(Number(t) * 1000).toISOString().slice(5, 16).replace("T", " "),
    },
  };
}

function useResize(ref: React.RefObject<HTMLDivElement | null>, chart: React.RefObject<IChartApi | null>) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => chart.current?.applyOptions({ width: el.clientWidth, height: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref, chart]);
}

/** 4h candles around a signal, with entry / target / stop lines and entry + exit markers. */
export function SignalChart({ candles, signal, theme }: { candles: Candle[]; signal: Signal; theme: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  useResize(ref, chart);

  useEffect(() => {
    const el = ref.current;
    if (!el || !candles.length) return;
    const c = createChart(el, baseOptions(el));
    chart.current = c;
    const series = c.addSeries(CandlestickSeries, {
      upColor: cssColor("long"), downColor: cssColor("short"), borderVisible: false,
      wickUpColor: cssColor("long", 0.8), wickDownColor: cssColor("short", 0.8),
      priceFormat: { type: "price", precision: signal.entry_price >= 100 ? 2 : signal.entry_price >= 1 ? 4 : 6, minMove: signal.entry_price >= 100 ? 0.01 : signal.entry_price >= 1 ? 0.0001 : 0.000001 },
    });
    series.setData(candles.map((k) => ({ time: k.t as UTCTimestamp, open: k.o, high: k.h, low: k.l, close: k.c })));
    const line = (price: number, color: string, title: string, style = LineStyle.Solid) =>
      series.createPriceLine({ price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title });
    line(signal.take_profit, cssColor("long"), "TP");
    line(signal.stop_loss, cssColor("short"), "SL");
    line(signal.entry_price, cssColor("accent"), "Entry", LineStyle.Dashed);
    const markers: SeriesMarker<Time>[] = [
      {
        time: (Math.floor(new Date(signal.signal_open_at).getTime() / 1000)) as UTCTimestamp,
        position: signal.side === "LONG" ? "belowBar" : "aboveBar",
        color: cssColor("accent"),
        shape: signal.side === "LONG" ? "arrowUp" : "arrowDown",
        text: signal.side,
      },
    ];
    if (signal.exit_at) {
      const t = Math.floor((new Date(signal.exit_at).getTime() - 1) / 1000 / 14400) * 14400;
      markers.push({
        time: t as UTCTimestamp,
        position: "aboveBar",
        color: signal.exit_reason === "TP" ? cssColor("long") : signal.exit_reason === "SL" ? cssColor("short") : cssColor("warn"),
        shape: "circle",
        text: signal.exit_reason ?? "",
      });
    }
    createSeriesMarkers(series, markers.sort((a, b) => Number(a.time) - Number(b.time)));
    const sigT = new Date(signal.signal_open_at).getTime() / 1000;
    const idx = candles.findIndex((k) => k.t >= sigT);
    if (idx >= 0) c.timeScale().setVisibleLogicalRange({ from: Math.max(0, idx - 60), to: Math.min(candles.length + 4, idx + 70) });
    return () => {
      c.remove();
      chart.current = null;
    };
  }, [candles, signal, theme]);

  return <div ref={ref} className="h-[360px] w-full sm:h-[420px]" />;
}

/** Account curve (compounded at a fixed risk per signal) with the drawdown underneath. */
export function EquityChart({ data, theme }: { data: Equity; theme: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  useResize(ref, chart);

  useEffect(() => {
    const el = ref.current;
    if (!el || !data.points.length) return;
    const c = createChart(el, { ...baseOptions(el), rightPriceScale: { borderColor: cssColor("line"), scaleMargins: { top: 0.1, bottom: 0.05 } } });
    chart.current = c;
    // one point per timestamp (several signals can close in the same minute)
    const byTime = new Map<number, { eq: number; dd: number }>();
    for (const p of data.points) byTime.set(Math.floor(new Date(p.t).getTime() / 1000), { eq: (p.equity - 1) * 100, dd: -p.drawdown_pct });
    const pts = [...byTime.entries()].sort((a, b) => a[0] - b[0]);
    const area = c.addSeries(AreaSeries, {
      lineColor: cssColor("accent"), topColor: cssColor("accent", 0.28), bottomColor: cssColor("accent", 0.02), lineWidth: 2,
      priceFormat: { type: "custom", formatter: (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%` },
    });
    area.setData(pts.map(([t, v]) => ({ time: t as UTCTimestamp, value: v.eq })));
    const dd = c.addSeries(HistogramSeries, {
      color: cssColor("short", 0.55),
      priceFormat: { type: "custom", formatter: (v: number) => `${v.toFixed(2)}%` },
    }, 1);
    dd.setData(pts.map(([t, v]) => ({ time: t as UTCTimestamp, value: v.dd })));
    c.panes()[1]?.setHeight(Math.round(el.clientHeight * 0.26));
    c.timeScale().fitContent();
    return () => {
      c.remove();
      chart.current = null;
    };
  }, [data, theme]);

  return <div ref={ref} className="h-[340px] w-full" />;
}
