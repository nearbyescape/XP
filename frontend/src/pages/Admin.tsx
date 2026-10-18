import clsx from "clsx";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, LogOut, Play, RefreshCw, Send, ShieldCheck } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api, ApiError } from "@/lib/api";
import { ago, duration, num, utc } from "@/lib/format";
import type { AdminOverview, Mode } from "@/lib/types";
import { Badge, Card, CardHeader, Dot, Empty, Select, Skeleton } from "@/components/ui";
import { StrategyChip } from "@/components/bits";

function Login() {
  const qc = useQueryClient();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const login = useMutation({
    mutationFn: () => api.admin.login(username, password),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin"] }),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate();
  };
  return (
    <div className="mx-auto max-w-sm py-10">
      <Card className="card-pad">
        <div className="mb-5 flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-lg bg-accent/15 text-accent"><KeyRound size={18} /></div>
          <div>
            <h1 className="font-semibold">Admin console</h1>
            <p className="text-xs text-muted">Engine health, strategy modes and Telegram delivery</p>
          </div>
        </div>
        <form onSubmit={submit} className="space-y-3">
          <label className="block"><span className="label">Username</span><input className="input mt-1.5" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} /></label>
          <label className="block"><span className="label">Password</span><input className="input mt-1.5" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus /></label>
          {login.error && <p className="text-sm text-short">{(login.error as ApiError).message}</p>}
          <button className="btn btn-primary w-full" disabled={login.isPending || !password}>{login.isPending ? "Signing in…" : "Sign in"}</button>
        </form>
      </Card>
    </div>
  );
}

function Health({ ov }: { ov: AdminOverview }) {
  const e = ov.engine;
  const items: [string, React.ReactNode][] = [
    ["Engine", <span className="inline-flex items-center gap-2"><Dot tone={e.alive ? "long" : "short"} pulse={e.alive} />{e.alive ? "running" : "offline"}{e.heartbeat_age_s !== null ? ` · ${num(e.heartbeat_age_s, 0)}s ago` : ""}</span>],
    ["Data source", `${e.source ?? "—"}${e.simulated ? " (simulated clock)" : ""} · tracking ${e.fine_interval ?? "—"}`],
    ["Engine clock", e.clock ? `${utc(e.clock, true)} UTC` : "—"],
    ["Last evaluation", ov.last_eval?.candle ? `${utc(ov.last_eval.candle)} candle · ${ov.last_eval.skipped ? "skipped" : `${ov.last_eval.signals ?? 0} signal(s)`}` : "—"],
    ["Model", e.model ? `${e.model} · threshold ${num(e.model_threshold ?? null, 3)}` : "not loaded"],
    ["Uptime", e.uptime_s ? duration(e.uptime_s) : "—"],
    ["Version", e.version ?? "—"],
    ["Search indexing", ov.config.search_indexing ? "allowed" : "blocked (noindex)"],
  ];
  return (
    <Card>
      <CardHeader title="Engine" hint={`${ov.config.universe.length} markets · default risk ${ov.config.risk_pct}%`} />
      <dl className="divide-y divide-line/60 px-4 sm:px-5">
        {items.map(([k, v]) => <div key={k} className="flex justify-between gap-4 py-2.5 text-sm"><dt className="text-muted">{k}</dt><dd className="num text-right">{v}</dd></div>)}
      </dl>
    </Card>
  );
}

function Gauge({ value, min, label, fmt, armed }: { value: number | null; min: number; label: string; fmt: (x: number) => string; armed: boolean }) {
  const ok = value === null || value >= min;
  return (
    <div>
      <div className="flex justify-between text-2xs text-muted"><span>{label}</span><span className="num">{value === null ? "—" : fmt(value)} <span className="text-faint">/ min {fmt(min)}</span></span></div>
      <div className="mt-1 h-1.5 rounded-full bg-raised ring-1 ring-line">
        <div className={clsx("h-full rounded-full", !armed ? "bg-faint" : ok ? "bg-long" : "bg-short")} style={{ width: `${value === null ? 0 : Math.min(100, (value / (min * 1.25)) * 100)}%` }} />
      </div>
    </div>
  );
}

function Strategies({ ov }: { ov: AdminOverview }) {
  const qc = useQueryClient();
  const set = useMutation({
    mutationFn: (v: { code: string; mode?: string; resume?: boolean }) => api.admin.setStrategy(v.code, { mode: v.mode, resume: v.resume }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin"] });
      qc.invalidateQueries({ queryKey: ["meta"] });
    },
  });
  return (
    <Card>
      <CardHeader title="Strategies" hint="Live = published · Shadow = generated and tracked, not published · Off = not evaluated" />
      <div className="divide-y divide-line/60">
        {ov.strategies.map((s) => (
          <div key={s.code} className="grid gap-4 px-4 py-4 sm:grid-cols-[1fr_1.3fr_auto] sm:items-center sm:px-5">
            <div className="flex items-center gap-3">
              <StrategyChip code={s.code} full />
              {s.auto_paused ? <Badge tone="warn" title={s.pause_reason ?? ""}>Auto-paused</Badge> : s.mode === "live" ? <Badge tone="long">Live</Badge> : s.mode === "shadow" ? <Badge tone="accent">Shadow</Badge> : <Badge>Off</Badge>}
              <span className="num text-xs text-faint">{s.active} open · {s.closed} closed</span>
            </div>
            <div className="space-y-2">
              <Gauge armed={s.rolling.signals >= s.rolling.window}
                label={s.rolling.signals >= s.rolling.window ? `Win rate, last ${s.rolling.window}` : `Win rate, ${s.rolling.signals}/${s.rolling.window} (kill switch arms at ${s.rolling.window})`}
                value={s.rolling.win_rate} min={s.rolling.min_win_rate} fmt={(x) => `${num(x, 1)}%`} />
              <Gauge armed={s.rolling.signals >= s.rolling.window} label="Profit factor" value={s.rolling.profit_factor} min={s.rolling.min_profit_factor} fmt={(x) => num(x)} />
              {s.auto_paused && <p className="text-xs text-warn">{s.pause_reason}</p>}
            </div>
            <div className="flex items-center gap-2">
              <Select label={`${s.code} mode`} value={s.mode ?? "live"} onChange={(mode) => set.mutate({ code: s.code, mode: mode as Mode })}>
                <option value="live">Live</option>
                <option value="shadow">Shadow</option>
                <option value="off">Off</option>
              </Select>
              {s.auto_paused && <button className="btn" onClick={() => set.mutate({ code: s.code, resume: true })}><Play size={14} /> Resume</button>}
            </div>
          </div>
        ))}
      </div>
      {set.error && <p className="px-5 pb-4 text-sm text-short">{(set.error as Error).message}</p>}
    </Card>
  );
}

function Telegram({ ov }: { ov: AdminOverview }) {
  const [chat, setChat] = useState("");
  const test = useMutation({ mutationFn: () => api.admin.telegramTest(chat || undefined) });
  const t = ov.telegram;
  return (
    <Card>
      <CardHeader title="Telegram" hint="Bot token from @BotFather · the bot must be an admin of the channel" />
      <div className="space-y-4 p-4 sm:p-5">
        {!t.enabled ? (
          <p className="text-sm text-muted">Disabled. Set <code className="num text-ink">TELEGRAM_BOT_TOKEN</code> and <code className="num text-ink">TELEGRAM_CHANNEL_ID</code>, then restart the engine.</p>
        ) : (
          <dl className="grid grid-cols-2 gap-y-2 text-sm">
            <dt className="text-muted">Bot</dt><dd className="num text-right">{t.bot?.bot ? `@${t.bot.bot}` : t.bot?.error ? <span className="text-short">{t.bot.error}</span> : "connecting…"}</dd>
            <dt className="text-muted">Channel</dt><dd className="num text-right">{t.channel_id ?? "—"}</dd>
            <dt className="text-muted">DM subscribers</dt><dd className="num text-right">{t.dm_enabled ? t.subscribers : "disabled"}</dd>
            <dt className="text-muted">Ops alerts</dt>
            <dd className="num text-right">{t.admin_chats ? `${t.admin_chats} admin chat${t.admin_chats > 1 ? "s" : ""}` : <span className="text-warn" title="Set TELEGRAM_ADMIN_CHAT_IDS (send /id to the bot)">off</span>}</dd>
            <dt className="text-muted">Queue</dt><dd className="num text-right">{t.queue.pending ?? 0} pending · {t.queue.sent ?? 0} sent · <span className={(t.queue.failed ?? 0) ? "text-short" : ""}>{t.queue.failed ?? 0} failed</span></dd>
          </dl>
        )}
        <div className="flex gap-2">
          <input className="input" placeholder={t.channel_id ?? "chat id or @channel"} value={chat} onChange={(e) => setChat(e.target.value)} disabled={!t.enabled} />
          <button className="btn shrink-0" disabled={!t.enabled || test.isPending} onClick={() => test.mutate()}><Send size={14} /> Test</button>
        </div>
        {test.isSuccess && <p className="text-xs text-long">Queued for {test.data.chat_id}. Delivered by the engine within a few seconds.</p>}
        {test.error && <p className="text-xs text-short">{(test.error as Error).message}</p>}
      </div>
    </Card>
  );
}

function Events({ ov }: { ov: AdminOverview }) {
  return (
    <Card>
      <CardHeader title="Engine events" hint="Most recent first" />
      {!ov.events.length ? <Empty title="No events yet" /> : (
        <div className="max-h-[440px] overflow-y-auto">
          <table className="w-full text-sm">
            <tbody>
              {ov.events.map((e) => (
                <tr key={e.id} className="table-row align-top">
                  <td className="num whitespace-nowrap px-4 py-2 text-xs text-faint sm:px-5" title={e.ts}>{ago(e.ts)}</td>
                  <td className="px-2 py-2"><Badge tone={e.level === "error" ? "short" : e.level === "warning" ? "warn" : "neutral"}>{e.kind}</Badge></td>
                  <td className="px-3 py-2 text-muted sm:pr-5">{e.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export default function Admin() {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["admin", "me"], queryFn: api.admin.me, retry: false });
  const ov = useQuery({ queryKey: ["admin", "overview"], queryFn: api.admin.overview, enabled: me.isSuccess, refetchInterval: 15_000 });
  const logout = useMutation({ mutationFn: api.admin.logout, onSuccess: () => qc.resetQueries({ queryKey: ["admin"] }) });

  if (me.isLoading) return <Skeleton className="mx-auto h-64 max-w-sm" />;
  if (me.error) {
    const status = (me.error as ApiError).status;
    if (status === 401) return <Login />;
    return <Card><Empty title="Admin unavailable">{(me.error as Error).message}</Empty></Card>;
  }
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <ShieldCheck className="text-accent" size={22} />
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Admin console</h1>
            <p className="text-sm text-muted">Signed in as {me.data?.username}</p>
          </div>
        </div>
        <div className="flex gap-2">
          <button className="btn" onClick={() => ov.refetch()}><RefreshCw size={14} className={ov.isFetching ? "animate-spin" : ""} /> Refresh</button>
          <button className="btn" onClick={() => logout.mutate()}><LogOut size={14} /> Sign out</button>
        </div>
      </div>
      {!ov.data ? <Skeleton className="h-96" /> : (
        <>
          <div className="grid gap-6 lg:grid-cols-2">
            <Health ov={ov.data} />
            <Telegram ov={ov.data} />
          </div>
          <Strategies ov={ov.data} />
          <Events ov={ov.data} />
        </>
      )}
    </div>
  );
}
