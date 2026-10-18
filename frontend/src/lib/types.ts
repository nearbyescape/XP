// Mirrors backend/app/api/serialize.py and backend/app/api/public.py

export type Side = "LONG" | "SHORT";
export type ExitReason = "TP" | "SL" | "BE" | "TIME";
export type Mode = "live" | "shadow" | "off";

export interface Benchmark {
  period: string;
  signals: number;
  win_rate: number; // fraction
  breakeven_win_rate: number;
  profit_factor: number;
  net_pct: number;
  avg_win_pct: number;
  avg_loss_pct: number;
  cagr_at_half_pct_risk?: number;
  max_dd_at_half_pct_risk?: number;
  tp1_rate?: number; // fraction of signals reaching TP1 / TP2 / TP3
  tp2_rate?: number;
  tp3_rate?: number;
}

export interface StrategyMeta {
  code: string;
  letter: string;
  name: string;
  kind: "rules" | "model";
  summary: string;
  rules: string;
  tp_atr: number;
  sl_atr: number;
  max_bars: number;
  targets_atr: number[];
  target_sizes: number[]; // fractions, TP1 first
  breakeven: boolean;
  benchmark: Benchmark;
  mode: Mode | null;
  auto_paused: boolean;
  pause_reason: string | null;
}

export interface Meta {
  app_name: string;
  version: string;
  environment: string;
  demo: boolean;
  source: string;
  universe: string[];
  interval: string;
  strategies: StrategyMeta[];
  book_benchmark: Benchmark;
  model: { version: string; threshold: number } | null;
  telegram: { enabled: boolean; channel_url: string | null; bot_username: string | null };
  default_risk_pct: number;
  risk: {
    risk_pct: number; // suggested risk per signal, % of the account
    max_open_risk_pct: number; // member rule: total across signals still before TP1
    note_signals: number; // signal posts note high open risk from this many before TP1
  };
  publishing: { paused: boolean }; // administrator's pause of all new signals
  costs: { entry: number; tp: number; exit: number };
  session: {
    tz: string; // IANA, e.g. Asia/Kolkata
    tz_abbr: string; // e.g. IST
    start: string; // "09:00"
    end: string;
    open: boolean;
    next_open: string;
    next_close: string;
    next_check: string; // next 4H close that publishes
    checks: string[]; // e.g. ["09:30 AM", "01:30 PM", ...]
    entry_window_minutes: number;
  };
  server_time: string;
  clock: string;
  next_candle_close: string;
  last_eval: { candle?: string; at?: string; signals?: number; skipped?: boolean };
  engine: { alive: boolean; heartbeat_age_s: number | null };
}

export interface Target {
  n: number;
  price: number;
  size_pct: number; // share of the position closed at this target
  pct: number; // distance from entry, percent
  hit_at: string | null;
  fill_price: number | null;
}

export interface Signal {
  id: number;
  uid: string;
  origin: "live" | "demo" | "backfill";
  strategy: string;
  strategy_name: string;
  symbol: string;
  side: Side;
  status: "ACTIVE" | "CLOSED";
  published: boolean;
  mode: string;
  signal_open_at: string;
  entry_at: string;
  expires_at: string;
  entry_price: number;
  take_profit: number; // TP1
  stop_loss: number; // planned stop
  stop_current: number; // stop in force (entry once TP1 is hit)
  breakeven: boolean;
  targets: Target[];
  targets_hit: number;
  tp1_at: string | null;
  risk_at_entry: number | null; // published signals before TP1 when this one was published, itself included
  take_profit_2: number | null;
  take_profit_3: number | null;
  atr: number;
  tp_atr: number;
  sl_atr: number;
  max_bars: number;
  tp_pct: number;
  sl_pct: number;
  reward_risk: number | null;
  regime_coin: number;
  regime_btc: number;
  model_prob: number | null;
  model_version: string | null;
  exit_reason: ExitReason | null;
  exit_price: number | null;
  exit_at: string | null;
  pnl_gross_pct: number | null;
  pnl_net_pct: number | null;
  r_multiple: number | null;
  mfe_pct: number | null;
  mae_pct: number | null;
  last_price: number | null;
  unrealized_pct: number | null;
  progress: number | null;
  last_checked_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Page<T> {
  total: number;
  items: T[];
}

export interface Kpis {
  signals: number;
  wins: number;
  losses: number;
  win_rate: number | null; // percent
  breakeven_win_rate: number | null;
  avg_win: number | null; // percent
  avg_loss: number | null;
  profit_factor: number | null;
  expectancy: number | null; // percent
  avg_r: number | null;
  total_r: number;
  max_consecutive_losses: number;
  signals_per_day: number | null;
  by_reason: Partial<Record<ExitReason, number>>;
  tp1_rate: number | null; // percent of signals reaching each target
  tp2_rate: number | null;
  tp3_rate: number | null;
}

export interface Stats {
  strategy: string;
  days: number | null;
  origin: string;
  since: string | null;
  first_entry_at: string | null;
  open_signals: number;
  kpis: Kpis;
  by_strategy: Record<string, Kpis>;
  benchmark: Benchmark;
}

export interface Equity {
  strategy: string;
  risk_pct: number;
  total_return_pct: number;
  max_drawdown_pct: number;
  points: { t: string; equity: number; drawdown_pct: number }[];
}

export interface MonthRow {
  month: string;
  signals: number;
  win_rate: number | null;
  profit_factor: number | null;
  total_r: number;
  expectancy: number | null;
}

export interface RegimeItem {
  coin: number;
  btc: number;
  close: number;
  change_24h: number | null;
  rsi2: number;
  atr_pct: number;
  candle_open: string;
}

export interface Candle {
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export interface Prices {
  at: string | null;
  prices: Record<string, number>;
}

export interface AdminOverview {
  engine: Record<string, unknown> & {
    alive: boolean;
    heartbeat_age_s: number | null;
    source?: string;
    clock?: string;
    simulated?: boolean;
    version?: string;
    model?: string | null;
    model_threshold?: number | null;
    uptime_s?: number;
    fine_interval?: string;
    candles?: Record<string, string>;
  };
  last_eval: Meta["last_eval"] | null;
  strategies: {
    code: string;
    name: string;
    mode: Mode | null;
    auto_paused: boolean;
    pause_reason: string | null;
    paused_at: string | null;
    rolling: {
      signals: number;
      win_rate: number | null;
      profit_factor: number | null;
      window: number;
      min_win_rate: number;
      min_profit_factor: number;
    };
    active: number;
    closed: number;
  }[];
  telegram: {
    enabled: boolean;
    channel_id: string | null;
    channel_url: string | null;
    dm_enabled: boolean;
    bot: { bot?: string | null; ok?: boolean; error?: string; at?: string } | null;
    subscribers: number;
    admin_chats: number;
    queue: Record<string, number>;
  };
  events: { id: number; ts: string; level: string; kind: string; message: string }[];
  publishing: { paused?: boolean; by?: string; at?: string };
  risk_watch: {
    at?: string;
    levels?: Record<string, WatchLevel>;
    measures?: Record<string, WatchMeasure>;
  };
  config: { source: string; universe: string[]; risk_pct: number; search_indexing: boolean; public_base_url: string };
}

export type WatchLevel = "watch" | "critical" | null;

export interface WatchMeasure {
  label: string;
  value: number | null;
  unit: string;
  level: WatchLevel;
  watch: number;
  critical: number | null;
}
