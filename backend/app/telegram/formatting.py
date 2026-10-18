"""Telegram message templates (HTML parse mode)."""

from __future__ import annotations

from datetime import datetime
from html import escape

from ..core.catalog import STRATEGIES
from ..models import Signal

TREND = {1: "▲", -1: "▼", 0: "▬"}
OUTCOME = {"TP": ("✅", "Target hit"), "SL": ("🛑", "Stop hit"), "TIME": ("⏱", "Time exit")}


def price(x: float | None) -> str:
    if x is None:
        return "—"
    a = abs(x)
    digits = 2 if a >= 100 else 4 if a >= 1 else 5 if a >= 0.01 else 8
    return f"{x:,.{digits}f}"


def pct(x: float | None, digits: int = 2, sign: bool = True) -> str:
    if x is None:
        return "—"
    return f"{x * 100:+.{digits}f}%" if sign else f"{x * 100:.{digits}f}%"


def pair(symbol: str) -> str:
    return f"{symbol[:-4]}/USDT" if symbol.endswith("USDT") else symbol


def base_asset(symbol: str) -> str:
    return symbol[:-4] if symbol.endswith("USDT") else symbol


def duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m"


def when(t: datetime) -> str:
    return f"{t:%d %b %H:%M} UTC"


def signal_url(base_url: str | None, signal_id: int) -> str | None:
    if not base_url or base_url.startswith(("http://localhost", "http://127.")):
        return None
    return f"{base_url.rstrip('/')}/signals/{signal_id}"


def signal_keyboard(base_url: str | None, signal_id: int) -> dict | None:
    url = signal_url(base_url, signal_id)
    return {"inline_keyboard": [[{"text": "Open signal ↗", "url": url}]]} if url else None


def new_signal(sig: Signal, risk_pct: float) -> str:
    spec = STRATEGIES[sig.strategy]
    long = sig.side == 1
    tp_pct = abs(sig.take_profit / sig.entry_price - 1)
    sl_pct = abs(sig.stop_loss / sig.entry_price - 1)
    notional = min(20.0, risk_pct / (sl_pct * 100) * 100) if sl_pct else 0.0
    bench = spec.benchmark
    lines = [
        f"{'🟢' if long else '🔴'} <b>{'LONG' if long else 'SHORT'} · {escape(pair(sig.symbol))}</b>"
        f"  ·  {escape(spec.name)} <code>{spec.code}</code>",
        "",
        f"Entry    <code>{price(sig.entry_price)}</code>   4H open {sig.entry_at:%H:%M} UTC",
        f"Target   <code>{price(sig.take_profit)}</code>   +{tp_pct * 100:.2f}%  · limit",
        f"Stop     <code>{price(sig.stop_loss)}</code>   −{sl_pct * 100:.2f}%",
        f"Expires  {when(sig.expires_at)}",
        "",
        f"Size  risk {risk_pct:g}% of equity → ~{notional:.1f}% notional, 1×",
        f"Regime  BTC {TREND[sig.regime_btc]} · {escape(base_asset(sig.symbol))} {TREND[sig.regime_coin]}"
        + (f"  ·  model {sig.model_prob:.3f}" if sig.model_prob is not None else ""),
        f"<i>Backtest 2022–26: {bench['win_rate'] * 100:.0f}% hit · {bench['net_pct']:+.2f}%/signal</i>",
        f"#{escape(sig.symbol)} #{spec.code.split('-')[0]}  ·  ID {sig.id}",
    ]
    return "\n".join(lines)


def closed_status_line(sig: Signal) -> str:
    icon, label = OUTCOME.get(sig.exit_reason or "", ("•", "Closed"))
    return f"{icon} <b>{label}</b> · net {pct(sig.pnl_net)} ({sig.r_multiple:+.2f}R)"


def close_signal(sig: Signal) -> str:
    icon, label = OUTCOME.get(sig.exit_reason or "", ("•", "Closed"))
    held = (sig.exit_at - sig.entry_at).total_seconds() if sig.exit_at else 0
    return (f"{icon} <b>{label}</b> · {escape(pair(sig.symbol))} {'LONG' if sig.side == 1 else 'SHORT'} · "
            f"<code>{sig.strategy}</code>\n"
            f"Exit <code>{price(sig.exit_price)}</code> · net <b>{pct(sig.pnl_net)}</b> "
            f"({sig.r_multiple:+.2f}R) · held {duration(held)}")


def edited_original(sig: Signal, risk_pct: float) -> str:
    return new_signal(sig, risk_pct) + "\n\n" + closed_status_line(sig)


def kpi_block(title: str, k: dict) -> str:
    if not k.get("signals"):
        return f"<b>{escape(title)}</b>\nNo closed signals yet."
    pf = "n/a" if k["profit_factor"] is None else f"{k['profit_factor']:.2f}"
    return (f"<b>{escape(title)}</b>\n"
            f"Signals {k['signals']} · win rate {k['win_rate'] * 100:.1f}%\n"
            f"Net/signal {pct(k['expectancy'])} · PF {pf} · {k['total_r']:+.1f}R")


def open_signals(rows: list[Signal]) -> str:
    if not rows:
        return "No open signals right now. New signals are evaluated at every 4H close (00/04/08/12/16/20 UTC)."
    out = [f"<b>Open signals ({len(rows)})</b>"]
    for s in rows:
        live = s.last_price or s.entry_price
        upnl = s.side * (live / s.entry_price - 1)
        out.append(f"{'🟢' if s.side == 1 else '🔴'} {escape(pair(s.symbol))} <code>{s.strategy}</code> · "
                   f"entry {price(s.entry_price)} · now {pct(upnl)}")
    return "\n".join(out)


def regime(snapshot: dict) -> str:
    if not snapshot:
        return "Regime data is not available yet."
    btc = snapshot.get("BTCUSDT", {})
    head = {1: "BULL — longs active", -1: "BEAR — shorts active", 0: "NEUTRAL — few signals"}
    out = [f"<b>Market regime</b>: BTC {TREND[btc.get('coin', 0)]} {head[btc.get('coin', 0)]}", ""]
    for sym, r in snapshot.items():
        out.append(f"{TREND[r['coin']]} {escape(base_asset(sym)):<5} {price(r['close'])} "
                   f"({pct(r.get('change_24h'))} 24h)")
    return "\n".join(out)


def welcome(app_name: str, channel_url: str | None, subscribed: bool) -> str:
    lines = [
        f"<b>{escape(app_name)}</b> — rule-based and ML-ranked crypto signals on the 4H chart.",
        "",
        "• Three validated strategies: Regime Pullback, Sweep Reversal, ML-Ranked",
        "• Every signal has a fixed target, stop and time limit; every result is published",
        "• Signals arrive at 4H closes (00/04/08/12/16/20 UTC) when the market allows",
        "",
        "You'll receive new signals and their results here." if subscribed
        else "Send /subscribe to receive signals here.",
    ]
    if channel_url:
        lines += ["", f"Channel: {escape(channel_url)}"]
    lines += ["", "/signals open signals · /stats performance · /regime market · /help",
              "", "<i>Not investment advice. Size every trade by its stop.</i>"]
    return "\n".join(lines)


HELP = ("<b>Commands</b>\n"
        "/signals — open signals\n"
        "/stats — performance (30 days and all time)\n"
        "/regime — BTC and coin trend\n"
        "/subscribe — receive signals in this chat\n"
        "/unsubscribe — stop receiving signals\n"
        "/help — this message")

COMMANDS = [("signals", "Open signals"), ("stats", "Performance"), ("regime", "Market regime"),
            ("subscribe", "Receive signals here"), ("unsubscribe", "Stop receiving signals"),
            ("help", "Help")]


def digest(day: datetime, closed: list[Signal], k30: dict) -> str:
    wins = sum(1 for s in closed if (s.pnl_net or 0) > 0)
    lines = [f"<b>Daily summary · {day:%d %b %Y}</b>"]
    if closed:
        lines.append(f"{len(closed)} closed · {wins} wins · {len(closed) - wins} losses · "
                     f"net {sum(s.r_multiple or 0 for s in closed):+.2f}R")
        for s in closed[:12]:
            icon = OUTCOME.get(s.exit_reason or "", ("•", ""))[0]
            lines.append(f"{icon} {escape(pair(s.symbol))} <code>{s.strategy}</code> {pct(s.pnl_net)}")
    else:
        lines.append("No signals closed yesterday.")
    lines += ["", kpi_block("Last 30 days", k30)]
    return "\n".join(lines)
