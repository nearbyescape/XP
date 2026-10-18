import clsx from "clsx";
import { Activity, Menu, Moon, Send, Sun, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useMeta } from "@/lib/queries";
import { useTheme } from "@/lib/theme";
import { useLive } from "@/lib/live";
import { pair, pct, price, setTimeZone, stamp, tz } from "@/lib/format";
import { Countdown, Logo } from "./bits";
import { Dot } from "./ui";

const NAV = [
  { to: "/", label: "Overview", end: true },
  { to: "/signals", label: "Signals" },
  { to: "/performance", label: "Performance" },
  { to: "/strategies", label: "Strategies" },
  { to: "/calculator", label: "Calculator" },
];

function EngineStatus() {
  const { data: meta } = useMeta();
  const { status } = useLive();
  if (!meta) return null;
  const tone = !meta.engine.alive ? "short" : meta.demo ? "warn" : "long";
  const label = !meta.engine.alive ? "Engine offline" : meta.demo ? "Demo replay" : "Live";
  const src = meta.source.startsWith("binance") ? (meta.source.endsWith("futures") ? "Binance Futures" : "Binance") : "Historical data";
  return (
    <div className="hidden items-center gap-2 rounded-lg border border-line bg-raised px-2.5 py-1 text-xs text-muted md:flex" title={`stream: ${status}`}>
      <Dot tone={tone} pulse={meta.engine.alive} />
      <span className="font-medium text-ink">{label}</span>
      <span className="text-faint">·</span>
      <span>{src}</span>
    </div>
  );
}

/** Publishing session: open with a countdown to the next signal check, or closed until the next opening. */
function SessionStatus() {
  const { data: meta } = useMeta();
  if (!meta) return null;
  const s = meta.session;
  return (
    <div className="hidden items-center gap-2 text-xs text-muted lg:flex"
      title={`Signals are published for 4H candles closing between ${s.start} and ${s.end} ${s.tz_abbr}: ${s.checks.join(" · ")}`}>
      <Activity size={14} className="text-accent" />
      {meta.publishing.paused ? (
        <span className="text-warn">New signals paused · open signals still tracked</span>
      ) : meta.demo ? (
        <span>Demo clock <span className="num text-ink">{stamp(meta.clock)}</span> {tz()}</span>
      ) : s.open ? (
        <span>Session open · next check <span className="text-ink"><Countdown target={s.next_check} serverTime={meta.server_time} /></span></span>
      ) : (
        <span>Session closed · opens <span className="num text-ink">{stamp(s.next_open)}</span> {tz()}</span>
      )}
    </div>
  );
}

function Toasts() {
  const { toasts, dismiss } = useLive();
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[340px] max-w-[calc(100vw-2rem)] flex-col gap-2">
      {toasts.map(({ id, signal: s, kind }) => (
        <Link
          key={id}
          to={`/signals/${s.id}`}
          onClick={() => dismiss(id)}
          className="card pointer-events-auto animate-slideIn border-l-4 p-3.5"
          style={{ borderLeftColor: kind === "new" ? (s.side === "LONG" ? "rgb(var(--long))" : "rgb(var(--short))") : kind === "target" || (s.pnl_net_pct ?? 0) > 0 ? "rgb(var(--long))" : "rgb(var(--short))" }}
        >
          <div className="label">{{ new: "New signal", target: "Target hit", closed: "Signal closed" }[kind]}</div>
          <div className="mt-1 text-sm font-semibold">
            {s.side} {pair(s.symbol)} <span className="font-normal text-muted">· {s.strategy}</span>
          </div>
          <div className="num mt-0.5 text-xs text-muted">
            {kind === "new"
              ? `entry ${price(s.entry_price)} · ${s.targets.length > 1 ? "TP1" : "TP"} ${price(s.take_profit)} · SL ${price(s.stop_loss)}`
              : kind === "target"
                ? `TP${s.targets_hit} hit at ${price(s.targets[s.targets_hit - 1]?.fill_price ?? s.targets[s.targets_hit - 1]?.price)}${s.breakeven ? " · stop at entry" : ""}`
                : `${s.exit_reason === "BE" ? `TP${s.targets_hit} · rest at entry` : s.exit_reason === "TP" && s.targets.length > 1 ? "All targets" : s.exit_reason} · net ${pct(s.pnl_net_pct)}`}
          </div>
        </Link>
      ))}
    </div>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const { data: meta } = useMeta();
  const { theme, toggle } = useTheme();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  const name = meta?.app_name ?? "SignalDesk";
  if (meta?.session) setTimeZone(meta.session.tz, meta.session.tz_abbr);  // before the pages render times
  useEffect(() => {
    const page = loc.pathname.startsWith("/admin") ? "Admin"
      : NAV.find((n) => n.to !== "/" && loc.pathname.startsWith(n.to))?.label;
    document.title = page ? `${page} · ${name}` : name;
  }, [loc.pathname, name]);

  return (
    <div className="flex min-h-screen flex-col">
      {meta?.demo && (
        <div className="border-b border-warn/30 bg-warn/10 px-4 py-1.5 text-center text-xs text-warn">
          <b>Demo mode</b> — historical market data replayed through the live engine (clock {stamp(meta.clock, true)} {tz()}). These are not live signals.
        </div>
      )}
      <header className="sticky top-0 z-40 border-b border-line bg-bg/85 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-4 px-4 sm:px-6">
          <Link to="/" className="flex items-center gap-2.5" onClick={() => setOpen(false)}>
            <Logo className="h-7 w-7" />
            <span className="text-[15px] font-semibold tracking-tight">{name}</span>
          </Link>
          <nav className="ml-4 hidden items-center gap-1 md:flex">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end}
                className={({ isActive }) => clsx("rounded-md px-3 py-1.5 text-sm transition", isActive ? "bg-raised text-ink" : "text-muted hover:text-ink")}>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <SessionStatus />
            <EngineStatus />
            {meta?.telegram.channel_url && (
              <a href={meta.telegram.channel_url} target="_blank" rel="noopener noreferrer" className="btn hidden sm:inline-flex">
                <Send size={14} /> Telegram
              </a>
            )}
            <button className="btn px-2" onClick={toggle} aria-label="Toggle theme">{theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}</button>
            <button className="btn px-2 md:hidden" onClick={() => setOpen((o) => !o)} aria-label="Menu">{open ? <X size={15} /> : <Menu size={15} />}</button>
          </div>
        </div>
        {open && (
          <nav className="border-t border-line px-4 py-2 md:hidden">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end} onClick={() => setOpen(false)}
                className={({ isActive }) => clsx("block rounded-md px-3 py-2 text-sm", isActive ? "bg-raised text-ink" : "text-muted")}>
                {n.label}
              </NavLink>
            ))}
          </nav>
        )}
      </header>
      <main key={`${loc.pathname}|${meta?.session?.tz ?? ""}`} className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 sm:py-8">{children}</main>
      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-7xl flex-col gap-2 px-4 py-6 text-xs text-faint sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <span>© {new Date().getUTCFullYear()} {name} · v{meta?.version ?? "—"}{meta?.model ? ` · model ${meta.model.version}` : ""}</span>
          <span className="max-w-2xl sm:text-right">
            Research and education only, not investment advice. Signals use fixed targets and stops on 4H closes; size every trade by its stop. Crypto derivatives are high risk.
          </span>
        </div>
      </footer>
      <Toasts />
    </div>
  );
}
