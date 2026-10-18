"""Telegram message templates (HTML parse mode)."""

from __future__ import annotations

from datetime import datetime
from html import escape

from ..core.catalog import STRATEGIES
from ..core.position import fills_of, open_return, targets_of
from ..models import Signal

TREND = {1: "▲", -1: "▼", 0: "▬"}


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


def move(sig: Signal, px: float) -> float:
    return sig.side * (px / sig.entry_price - 1)


def size_pct(z: float) -> str:
    return f"{z * 100:.0f}%"


def outcome(sig: Signal) -> tuple[str, str]:
    """(icon, label) for a closed signal."""
    n, total = sig.targets_hit or 0, len(targets_of(sig))
    if sig.exit_reason == "TP":
        return ("🏆", f"All {total} targets hit") if total > 1 else ("✅", "Target hit")
    if sig.exit_reason == "BE":
        return "✅", f"TP{n} hit · rest closed at entry"
    if sig.exit_reason == "SL":
        return "🛑", "Stop hit"
    if sig.exit_reason == "TIME":
        return "⏱\ufe0f", "Time exit" + (f" after TP{n}" if n else "")
    return "•", "Closed"


def side_pair(sig: Signal) -> str:
    return f"{escape(pair(sig.symbol))} {'LONG' if sig.side == 1 else 'SHORT'} · <code>{sig.strategy}</code>"


def new_signal(sig: Signal, risk_pct: float) -> str:
    spec = STRATEGIES[sig.strategy]
    long = sig.side == 1
    targets = targets_of(sig)
    sl_pct = abs(sig.stop_loss / sig.entry_price - 1)
    notional = min(20.0, risk_pct / (sl_pct * 100) * 100) if sl_pct else 0.0
    bench = spec.benchmark
    lines = [
        f"{'🟢' if long else '🔴'} <b>{'LONG' if long else 'SHORT'} · {escape(pair(sig.symbol))}</b>",
        f"{escape(spec.name)} · <code>{spec.code}</code>",
        "",
        f"Entry    <code>{price(sig.entry_price)}</code>   4H open {sig.entry_at:%H:%M} UTC",
    ]
    if len(targets) == 1:
        lines.append(f"Target   <code>{price(targets[0][0])}</code>   {pct(move(sig, targets[0][0]))}  · limit")
    else:
        lines += [f"TP{i}      <code>{price(p)}</code>   {pct(move(sig, p))}  · {size_pct(z)}"
                  for i, (p, z) in enumerate(targets, 1)]
    lines += [
        f"Stop     <code>{price(sig.stop_loss)}</code>   −{sl_pct * 100:.2f}%",
        f"Expires  {when(sig.expires_at)}",
        "",
    ]
    if len(targets) > 1:
        lines.append("Targets are limit orders." + (" After TP1, move the stop to entry." if sig.breakeven else ""))
    hits = (f"TP1 {bench['tp1_rate'] * 100:.0f}% · TP2 {bench['tp2_rate'] * 100:.0f}% · "
            f"TP3 {bench['tp3_rate'] * 100:.0f}%") if len(targets) > 1 and "tp1_rate" in bench \
        else f"{bench['win_rate'] * 100:.0f}% hit"
    lines += [
        f"Size  risk {risk_pct:g}% of equity → ~{notional:.1f}% notional, 1×",
        f"Regime  BTC {TREND[sig.regime_btc]} · {escape(base_asset(sig.symbol))} {TREND[sig.regime_coin]}"
        + (f"  ·  model {sig.model_prob:.3f}" if sig.model_prob is not None else ""),
        f"<i>Backtest 2022–26: {hits} · {bench['net_pct']:+.2f}%/signal</i>",
        f"#{escape(sig.symbol)} #{spec.code.split('-')[0]}  ·  ID {sig.id}",
    ]
    return "\n".join(lines)


def status_line(sig: Signal) -> str:
    """Progress stamped onto the original post: targets reached so far, or the final result."""
    if sig.status == "CLOSED":
        icon, label = outcome(sig)
        return f"{icon} <b>{label}</b> · net {pct(sig.pnl_net)} ({sig.r_multiple:+.2f}R)"
    n, targets = sig.targets_hit or 0, targets_of(sig)
    if not n:
        return ""
    left = 1 - sum(z for _, z in targets[:n])
    ticks = " ".join(f"TP{i} ✓" for i in range(1, n + 1))
    stop = " · stop at entry" if sig.breakeven else ""
    return f"🎯 <b>{ticks}</b> · {size_pct(left)} still open{stop}"


def target_update(sig: Signal, hit_before: int) -> str:
    """Reply when one or more targets fill and part of the position is still open."""
    targets, fills = targets_of(sig), fills_of(sig)
    new = range(hit_before, sig.targets_hit or 0)
    head = " + ".join(f"TP{i + 1}" for i in new)
    lines = [f"🎯 <b>{head} hit</b>", side_pair(sig)]
    for i in new:
        px = fills[i] if i < len(fills) else targets[i][0]
        lines.append(f"{size_pct(targets[i][1])} closed at <code>{price(px)}</code> ({pct(move(sig, px))})")
    left = 1 - sum(z for _, z in targets[:sig.targets_hit or 0])
    if hit_before == 0 and sig.breakeven:
        lines.append(f"Move the stop to entry <code>{price(sig.entry_price)}</code> · {size_pct(left)} still open")
    else:
        lines.append(f"{size_pct(left)} still open" + (" · stop at entry" if sig.breakeven else ""))
    return "\n".join(lines)


def close_signal(sig: Signal) -> str:
    icon, label = outcome(sig)
    held = (sig.exit_at - sig.entry_at).total_seconds() if sig.exit_at else 0
    exit_line = "" if sig.exit_reason == "TP" and len(targets_of(sig)) > 1 else \
        f"Exit <code>{price(sig.exit_price)}</code> · "
    return (f"{icon} <b>{label}</b>\n{side_pair(sig)}\n"
            f"{exit_line}net <b>{pct(sig.pnl_net)}</b> ({sig.r_multiple:+.2f}R) · held {duration(held)}")


def edited_original(sig: Signal, risk_pct: float) -> str:
    line = status_line(sig)
    return new_signal(sig, risk_pct) + (f"\n\n{line}" if line else "")


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
        n = getattr(s, "targets_hit", 0) or 0
        hits = f" · TP{n} ✓" if n else ""
        out.append(f"{'🟢' if s.side == 1 else '🔴'} {escape(pair(s.symbol))} <code>{s.strategy}</code> · "
                   f"entry {price(s.entry_price)} · now {pct(open_return(s, live))}{hits}")
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
        "• Every signal has three targets (TP1/TP2/TP3), a stop and a time limit; every result is published",
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


def alert(app_name: str, level: str, kind: str, message: str) -> str:
    icon = {"error": "🔴", "warning": "🟠"}.get(level, "🟢")
    return f"{icon} <b>{escape(app_name)}</b> · <code>{escape(kind)}</code>\n{escape(message)}"


def status(hb: dict, last_eval: dict, states: dict, open_count: int, queue: dict) -> str:
    when = lambda iso: f"{iso[:16].replace('T', ' ')} UTC" if iso else "—"  # noqa: E731
    evaluated = "skipped" if last_eval.get("skipped") else f"{last_eval.get('signals', 0)} signal(s)"
    lines = [
        "<b>Engine status</b>",
        f"Version {escape(str(hb.get('version', '?')))} · {escape(str(hb.get('source', '?')))}"
        f" · up {duration(hb.get('uptime_s') or 0)}",
        f"Clock: {when(hb.get('clock'))}",
        f"Last 4H evaluation: {when(last_eval.get('candle'))} · {evaluated}",
        f"Open signals: {open_count}",
        f"Telegram queue: {queue.get('pending', 0)} pending · {queue.get('failed', 0)} failed",
        "",
        "<b>Strategies</b>",
    ]
    for code, st in sorted(states.items()):
        mode = "auto-paused" if st.auto_paused else st.mode
        lines.append(f"<code>{code}</code> {mode}" + (f" — {escape(st.pause_reason)}" if st.pause_reason else ""))
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
        losses = len(closed) - wins
        lines.append(f"{len(closed)} closed · {wins} win{'' if wins == 1 else 's'} · "
                     f"{losses} loss{'' if losses == 1 else 'es'} · "
                     f"net {sum(s.r_multiple or 0 for s in closed):+.2f}R")
        for s in closed[:12]:
            hits = f" · TP{s.targets_hit}" if (s.targets_hit or 0) and len(targets_of(s)) > 1 else ""
            lines.append(f"{outcome(s)[0]} {escape(pair(s.symbol))} <code>{s.strategy}</code> {pct(s.pnl_net)}{hits}")
    else:
        lines.append("No signals closed yesterday.")
    lines += ["", kpi_block("Last 30 days", k30)]
    return "\n".join(lines)
