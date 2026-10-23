"""Telegram message templates (HTML parse mode).

Channel messages: the signal, one reply per target / stop hit, the session greeting and the session
summary. Levels are shown as prices with the share of the position closed at each target.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape

from ..core.catalog import BAR_SECONDS, STRATEGIES
from ..core.position import fills_of, open_return, targets_of
from ..core.risk import Exposure
from ..core.session import Session
from ..models import Signal

TREND = {1: "▲", -1: "▼", 0: "▬"}
MARKETS = {"binance_futures": "Binance USDT futures", "binance_spot": "Binance spot",
           "replay": "Binance (historical replay)"}
MAX_LINES = 15  # per list in the session messages


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


def signal_url(base_url: str | None, signal_id: int) -> str | None:
    if not base_url or base_url.startswith(("http://localhost", "http://127.")):
        return None
    return f"{base_url.rstrip('/')}/signals/{signal_id}"


def signal_keyboard(base_url: str | None, signal_id: int) -> dict | None:
    url = signal_url(base_url, signal_id)
    return {"inline_keyboard": [[{"text": "Open signal ↗", "url": url}]]} if url else None


def size_pct(z: float) -> str:
    return f"{z * 100:.0f}%"


@dataclass(frozen=True)
class Style:
    """What every channel message needs besides the signal itself."""
    brand: str
    session: Session
    market: str
    entry_window_minutes: int = 15
    risk_pct: float = 0.5           # suggested risk per signal, % of the account
    max_open_risk_pct: float = 5.0  # member rule: total across signals still before TP1
    risk_note_signals: int = 10     # signal posts note high open risk from this many before TP1
    website: bool = True            # members can open the website (false: the site is private)

    @classmethod
    def from_settings(cls, settings) -> Style:
        return cls(settings.app_name, Session.from_settings(settings),
                   MARKETS.get(settings.market_data_source, "Binance"), settings.entry_window_minutes,
                   settings.default_risk_pct, settings.max_open_risk_pct, settings.risk_note_signals,
                   not settings.site_private)


# ---------------------------------------------------------------------------------- signals
def public_id(sig: Signal) -> str:
    return hashlib.sha1(sig.uid.encode()).hexdigest()[:12]


def side_name(sig: Signal) -> str:
    return "LONG" if sig.side == 1 else "SHORT"


def ticker(sig: Signal) -> str:
    return f"{escape(sig.symbol)} {side_name(sig)}"


def setup(sig: Signal) -> str:
    spec = STRATEGIES[sig.strategy]
    if spec.kind == "model":
        detail = f"Model confidence {sig.model_prob * 100:.0f}%" if sig.model_prob is not None else "Model ranked"
    elif sig.regime_coin == sig.regime_btc and sig.regime_coin:
        detail = ("Uptrend" if sig.regime_coin == 1 else "Downtrend") + " (coin + BTC)"
    else:
        detail = f"Coin {TREND[sig.regime_coin]} · BTC {TREND[sig.regime_btc]}"
    return f"{escape(spec.name)} · {detail}"


def new_signal(sig: Signal, style: Style) -> str:
    targets = targets_of(sig)
    found = sig.signal_open_at + timedelta(seconds=BAR_SECONDS)  # the check that found the setup
    lines = [f"<b>{escape(style.brand)} Signal · {side_name(sig)}</b>"]
    if getattr(sig, "carried_from", None):
        lines.append(f"🌅 Overnight setup from the {style.session.label(found, with_date=False)} check, still valid · "
                     "entry at the morning price, targets and stop unchanged")
    lines += [
        f"{escape(sig.symbol)} · {escape(style.market)} · 4H",
        f"Setup: {setup(sig)}",
        f"Source close: {style.session.label(found)}",
        f"Entry: {price(sig.entry_price)}",
        f"Stop loss: {price(sig.stop_loss)}",
    ]
    if len(targets) == 1:
        lines.append(f"Take profit: {price(targets[0][0])}")
    else:
        lines += [f"TP{i} ({size_pct(z)}): {price(p)}" for i, (p, z) in enumerate(targets, 1)]
        if sig.breakeven:
            lines.append("After TP1: move remaining stop to entry")
    if sig.risk_at_entry and sig.risk_at_entry >= style.risk_note_signals:
        lines.append(f"⚠️ High open risk: {sig.risk_at_entry} signals before TP1, this one included · "
                     f"keep your total under {style.max_open_risk_pct:g}%")
    window = sig.entry_at + timedelta(minutes=style.entry_window_minutes)
    lines += [
        f"Entry window ends: {style.session.label(window)}",
        escape(STRATEGIES[sig.strategy].basis),
        f"Signal: {public_id(sig)}",
        "<i>Targets are reference levels; results are recorded at these levels, not your fills.</i>",
    ]
    return "\n".join(lines)


def outcome(sig: Signal) -> str:
    """Short outcome of a closed signal: 'TP3', 'TP2, then entry', 'stop loss', 'time exit'."""
    n, total = sig.targets_hit or 0, len(targets_of(sig))
    return {"TP": f"TP{total}" if total > 1 else "target hit", "SL": "stop loss", "BE": f"TP{n}, then entry",
            "TIME": "time exit" + (f" after TP{n}" if n else "")}.get(sig.exit_reason or "", "closed")


def progress(sig: Signal) -> str:
    """Status of an open signal: 'TP2 ✓ · 20% running, stop at entry' or 'waiting for TP1'."""
    n, targets = sig.targets_hit or 0, targets_of(sig)
    if not n:
        return "waiting for TP1" if len(targets) > 1 else "waiting for target"
    left = 1 - sum(z for _, z in targets[:n])
    return f"TP{n} ✓ · {size_pct(left)} running" + (", stop at entry" if sig.breakeven else "")


def edited_original(sig: Signal, style: Style) -> str:
    """The original post with its progress or final result (edits are silent)."""
    if sig.status == "CLOSED":
        line = f"Result: {outcome(sig)} · {pct(sig.pnl_net)}"
    elif sig.targets_hit:
        line = f"Status: {progress(sig)}"
    else:
        return new_signal(sig, style)
    return f"{new_signal(sig, style)}\n\n<b>{line}</b>"


def target_update(sig: Signal, hit_before: int) -> str:
    """Reply when TP1 / TP2 fill and part of the position is still running."""
    targets, fills = targets_of(sig), fills_of(sig)
    new = list(range(hit_before, sig.targets_hit or 0))
    fill = lambda i: fills[i] if i < len(fills) else targets[i][0]  # noqa: E731
    if len(new) == 1:
        i = new[0]
        lines = [f"✅ TP{i + 1} hit · {ticker(sig)} · {price(fill(i))} · {size_pct(targets[i][1])} closed"]
    else:
        lines = [f"✅ {' + '.join(f'TP{i + 1}' for i in new)} hit · {ticker(sig)}"]
        lines += [f"TP{i + 1} {price(fill(i))} · {size_pct(targets[i][1])} closed" for i in new]
    if hit_before == 0 and sig.breakeven:
        lines.append(f"Move remaining stop to entry: {price(sig.entry_price)}")
    return "\n".join(lines)


def close_signal(sig: Signal, hit_before: int | None = None) -> str:
    """Reply when the signal closes: final target, stop loss, stop at entry or time limit.
    `hit_before` = targets already announced, so targets filled in the same pass are named here."""
    n, total = sig.targets_hit or 0, len(targets_of(sig))
    new = list(range(n - 1 if hit_before is None else hit_before, n)) if n else []
    held = duration((sig.exit_at - sig.entry_at).total_seconds()) if sig.exit_at else "—"
    result = f"Result: {pct(sig.pnl_net)} · held {held}"
    if sig.exit_reason == "TP":
        hits = " + ".join(f"TP{i + 1}" for i in new) if total > 1 else "TP"
        return f"🏆 {hits} hit · {ticker(sig)} · signal complete\n{result}"
    if sig.exit_reason == "SL":
        return f"🛑 SL hit · {ticker(sig)} · {price(sig.exit_price)}\n{result}"
    if sig.exit_reason == "BE":
        head = (f"{' + '.join(f'TP{i + 1}' for i in new)} hit, then stop at entry" if hit_before is not None
                and new else f"Stop at entry hit after TP{n}")
        return f"🔒 {head} · {ticker(sig)}\n{result}"
    after = f" after TP{n}" if n else ""
    return f"⏱️ Time exit{after} · {ticker(sig)} · closed at {price(sig.exit_price)}\n{result}"


# ---------------------------------------------------------------------------------- session
EVENT_TEXT = {"TP1": "TP1 hit", "TP2": "TP2 hit", "TP3": "TP3 hit", "SL": "SL hit",
              "BE": "stop at entry hit", "TIME": "time exit"}


def _capped(lines: list[str]) -> list[str]:
    return lines if len(lines) <= MAX_LINES else lines[:MAX_LINES] + [f"… and {len(lines) - MAX_LINES} more"]


def _trend(snapshot: dict) -> str:
    t = (snapshot.get("BTCUSDT") or {}).get("coin", 0)
    return {1: "BTC in an uptrend ▲ · long setups active", -1: "BTC in a downtrend ▼ · short setups active",
            0: "BTC without a clear trend ▬ · fewer rule-based setups"}[t]


def _last30(k30: dict) -> str:
    if not k30.get("signals"):
        return "Last 30 days: no closed signals yet"
    pf = f" · PF {k30['profit_factor']:.2f}" if k30.get("profit_factor") else ""
    return f"Last 30 days: {k30['signals']} signals · {k30['win_rate'] * 100:.1f}% win rate{pf}"


def open_risk(exp: Exposure, style: Style) -> str:
    """'Open risk: 4 signals before TP1 (3 long / 1 short) · 2.0% at 0.5% each'."""
    if not exp.at_risk:
        return "Open risk: none · every open signal is past TP1, stops at entry"
    n = exp.at_risk
    line = (f"Open risk: {n} signal{'s' if n != 1 else ''} before TP1 ({exp.long} long / {exp.short} short) · "
            f"{n * style.risk_pct:.1f}% at {style.risk_pct:g}% each")
    if n * style.risk_pct > style.max_open_risk_pct:
        line += f" ⚠️ above the {style.max_open_risk_pct:g}% limit"
    return line


PAUSED = "⏸️ New signals are paused. Open signals are still tracked and updated."
QUIET = "<i>No setup met our entry rules today — we only trade when the odds are on our side.</i>"


def setup_forming(side: int, at: datetime, later: list[datetime], style: Style) -> str:
    """The AI model is close to a signal at an early check (app/engine/forming.py)."""
    s = style.session
    return "\n".join([
        "👀 <b>Setup forming</b>",
        "",
        f"Our AI model is close to a signal after the {s.label(at, with_date=False)} check, leaning "
        f"<b>{'LONG' if side == 1 else 'SHORT'}</b>.",
        "Not a signal yet — please don't enter early. If it confirms, it is posted here with entry, stop and "
        "targets.",
        "",
        "Next checks today: " + " · ".join(s.label(t, with_date=False) for t in later),
    ])

def session_start(now: datetime, style: Style, snapshot: dict, open_rows: list[Signal],
                  overnight: list[tuple[str, datetime, Signal]], k30: dict, exp: Exposure | None = None,
                  paused: bool = False) -> str:
    s = style.session
    local = s.local(now)
    checks = " · ".join(s.label(t, with_date=False) for t in s.checks(local.date()))
    lines = [
        f"☀️ <b>Good morning, {escape(style.brand)} session is open</b>",
        f"{local:%a, %d %b %Y} · {s.label(s.last_start(now), False)} – {s.label(s.next_end(now), False)} "
        f"{s.tzname(now)}",
        f"Market: {_trend(snapshot)}",
        PAUSED if paused else f"Signal checks: {checks}",
        "",
        f"<b>Open signals ({len(open_rows)})</b>" if open_rows else "No open signals.",
    ]
    lines += _capped([f"{ticker(r)} · {progress(r)}" for r in open_rows])
    if open_rows and exp is not None:
        lines.append(open_risk(exp, style))
    if overnight:
        lines += ["", "<b>Overnight</b>"]
        lines += _capped([f"{ticker(sig)} · {EVENT_TEXT[kind]} · {s.label(t, False)}" for kind, t, sig in overnight])
    lines += ["", _last30(k30)]
    return "\n".join(lines)


def session_end(now: datetime, style: Style, published: list[Signal], events: list[tuple[str, datetime, Signal]],
                closed: list[Signal], open_rows: list[Signal], k30: dict, exp: Exposure | None = None,
                paused: bool = False) -> str:
    s = style.session
    longs = sum(1 for r in published if r.side == 1)
    counts = {k: sum(1 for kind, _, _ in events if kind == k) for k in ("TP1", "TP2", "TP3", "SL", "BE")}
    lines = [
        f"🌙 <b>Session closed · {s.local(now):%a, %d %b %Y}</b>",
        "",
        f"Signals: {len(published)}" + (f" · {longs} LONG · {len(published) - longs} SHORT" if published else ""),
        f"Hits: TP1 ×{counts['TP1']} · TP2 ×{counts['TP2']} · TP3 ×{counts['TP3']} · SL ×{counts['SL']}"
        + (f" · stop at entry ×{counts['BE']}" if counts["BE"] else ""),
    ]
    if not published and not paused:  # a quiet day reads as discipline, not as a dead channel
        lines += ["", QUIET]
    if closed:
        wins = sum(1 for r in closed if (r.pnl_net or 0) > 0)
        avg = sum(r.pnl_net or 0 for r in closed) / len(closed)
        lines += ["", f"<b>Closed ({len(closed)})</b> · {wins} won · {len(closed) - wins} lost · average {pct(avg)}"]
        lines += _capped([f"{ticker(r)} · {outcome(r)} · {pct(r.pnl_net)}" for r in closed])
    if open_rows:
        lines += ["", f"<b>Open overnight ({len(open_rows)})</b>"]
        lines += _capped([f"{ticker(r)} · {progress(r)}" for r in open_rows])
        if exp is not None:
            lines.append(open_risk(exp, style))
    lines += ["", _last30(k30)]
    if paused:
        lines.append(PAUSED)
    lines.append(f"Next session: {s.label(s.next_start(now))}")
    return "\n".join(lines)


def rules(style: Style) -> str:
    """Member rules, pinned in the channel and sent by /rules."""
    most = int(round(style.max_open_risk_pct / style.risk_pct)) if style.risk_pct else 0
    return "\n".join([
        f"📌 <b>{escape(style.brand)} · member rules</b>",
        "",
        "1. Place your stop on the exchange as soon as you enter: a stop-market order, reduce-only. "
        "Never a mental stop.",
        f"2. Risk {style.risk_pct:g}% of your account per signal ({style.risk_pct / 2:g}% while you are new). "
        + ("The calculator on the website sizes the trade." if style.website else
           f"Position size = account × {style.risk_pct:g}% ÷ distance from entry to stop (in %); e.g. "
           f"10,000 × {style.risk_pct:g}% ÷ 7.5% = {10_000 * style.risk_pct / 7.5:,.0f}."),
        f"3. Keep your total open risk under {style.max_open_risk_pct:g}%. Signals still before TP1 count: "
        f"at {style.risk_pct:g}% each that is {most} signals.",
        "4. Use isolated margin. Sized this way the trade needs no extra leverage, so the stop sits far "
        "from liquidation.",
        "5. When TP1 fills, move the stop to entry. If the entry window has passed, skip the signal.",
        "",
        "<i>Results are recorded at the published levels. Not investment advice.</i>",
    ])


# ---------------------------------------------------------------------------------- bot commands
def kpi_block(title: str, k: dict) -> str:
    if not k.get("signals"):
        return f"<b>{escape(title)}</b>\nNo closed signals yet."
    pf = "n/a" if k["profit_factor"] is None else f"{k['profit_factor']:.2f}"
    return (f"<b>{escape(title)}</b>\n"
            f"Signals {k['signals']} · win rate {k['win_rate'] * 100:.1f}%\n"
            f"Net/signal {pct(k['expectancy'])} · PF {pf} · {k['total_r']:+.1f}R")


def open_signals(rows: list[Signal]) -> str:
    if not rows:
        return "No open signals right now."
    out = [f"<b>Open signals ({len(rows)})</b>"]
    for s in rows:
        live = s.last_price or s.entry_price
        out.append(f"{ticker(s)} · {progress(s)} · now {pct(open_return(s, live))}")
    return "\n".join(out)


def regime(snapshot: dict) -> str:
    if not snapshot:
        return "Regime data is not available yet."
    out = [f"<b>Market</b>: {_trend(snapshot)}", ""]
    for sym, r in snapshot.items():
        out.append(f"{TREND[r['coin']]} {escape(base_asset(sym)):<5} {price(r['close'])} "
                   f"({pct(r.get('change_24h'))} 24h)")
    return "\n".join(out)


def welcome(app_name: str, channel_url: str | None, subscribed: bool, session_text: str = "") -> str:
    lines = [
        f"<b>{escape(app_name)}</b> · rule-based and ML-ranked crypto signals on the 4H chart.",
        "",
        "• Three validated strategies: Regime Pullback, Sweep Reversal, ML-Ranked",
        "• Every signal has three targets (TP1/TP2/TP3) and a stop; every result is published",
    ]
    if session_text:
        lines.append(f"• Signals are posted during the session, {escape(session_text)}")
    lines += ["", "You'll receive new signals and their results here." if subscribed
              else "Follow the channel for signals and results."]
    if channel_url:
        lines += ["", f"Channel: {escape(channel_url)}"]
    lines += ["", "Read the member rules first: /rules",
              "", "/signals open signals · /stats performance · /regime market · /help",
              "", "<i>Not investment advice. Size every trade by its stop.</i>"]
    return "\n".join(lines)


def alert(app_name: str, level: str, kind: str, message: str) -> str:
    icon = {"error": "🔴", "warning": "🟠"}.get(level, "🟢")
    return f"{icon} <b>{escape(app_name)}</b> · <code>{escape(kind)}</code>\n{escape(message)}"


def status(hb: dict, last_eval: dict, states: dict, open_count: int, queue: dict,
           publishing: dict | None = None, watch: dict | None = None, session: Session | None = None) -> str:
    def when(iso: str | None, shift: timedelta = timedelta(0)) -> str:
        if not iso:
            return "—"
        t = datetime.fromisoformat(iso) + shift
        return session.label(t) if session else f"{t:%Y-%m-%d %H:%M} UTC"

    evaluated = "skipped" if last_eval.get("skipped") else f"{last_eval.get('signals', 0)} signal(s)"
    lines = [
        "<b>Engine status</b>",
        f"Version {escape(str(hb.get('version', '?')))} · {escape(str(hb.get('source', '?')))}"
        f" · up {duration(hb.get('uptime_s') or 0)}",
        f"Clock: {when(hb.get('clock'))}",
        # the candle is stored by its open time; the check happens at its close
        f"Last 4H check: {when(last_eval.get('candle'), timedelta(hours=4))} · {evaluated}",
        f"Open signals: {open_count}",
        f"Telegram queue: {queue.get('pending', 0)} pending · {queue.get('failed', 0)} failed",
        "",
        "<b>Strategies</b>",
    ]
    for code, st in sorted(states.items()):
        mode = "auto-paused" if st.auto_paused else st.mode
        lines.append(f"<code>{code}</code> {mode}" + (f" — {escape(st.pause_reason)}" if st.pause_reason else ""))
    if publishing and publishing.get("paused"):
        lines += ["", f"⏸️ <b>New signals paused</b> by {escape(str(publishing.get('by', '?')))} since "
                      f"{when(publishing.get('at'))}"]
    if watch and watch.get("measures"):
        lines += ["", "<b>Risk watch</b>"]
        for m in watch["measures"].values():
            value = "—" if m["value"] is None else f"{m['value']:g}{m['unit']}"
            flag = {"watch": " 🟠", "critical": " 🔴"}.get(m["level"] or "", "")
            lines.append(f"{escape(m['label'])}: {value}{flag}")
    lines += ["", "/pause · /resume — stop or restart new signals"]
    return "\n".join(lines)


HELP = ("<b>Commands</b>\n"
        "/signals — open signals\n"
        "/stats — performance (30 days and all time)\n"
        "/regime — BTC and coin trend\n"
        "/rules — member rules\n"
        "/help — this message")

COMMANDS = [("signals", "Open signals"), ("stats", "Performance"), ("regime", "Market regime"),
            ("rules", "Member rules"), ("help", "Help")]
