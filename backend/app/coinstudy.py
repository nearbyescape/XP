"""Coin study: which extra coins can run strategies A and B (python -m app.cli coin-study).

Run it on the server: it needs Binance. Read-only: it downloads 4H futures candles into memory,
replays the live A/B selection and trade lifecycle on them (app.core.replay, the engine's own code)
and prints a report. Nothing is written to the database or anywhere else. Strategy C stays on the
coins its model was trained on.

Rules, fixed before looking at any result:
  candidates  USDT-M perpetuals on a coin (no stablecoin, index or commodity contract), trading on
              futures since before LISTED_BEFORE, not already in the universe: the TOP by 24h volume
  pass        in the selection window (2022-01-01 .. SPLIT): at least MIN_SIGNALS signals, win rate
              >= MIN_WIN_RATE and profit factor >= MIN_PF
  verdict     the passing coins together in the check window (SPLIT .. now), which was not used to
              pick them: add them if that basket keeps win rate >= MIN_WIN_RATE and PF >= CHECK_PF
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from .config import Settings
from .core.catalog import RGP, RSR
from .core.lifecycle import Costs
from .core.replay import replay
from .core.session import Session
from .market.binance import BinanceMarketData
from .services.repo import CANDLE_COLS

LISTED_BEFORE = "2023-01-01"
START, SPLIT = "2022-01-01", "2025-01-01"
WARMUP = timedelta(days=150)       # indicators (EMA200 trend, ATR, 4-day range) settle before START
MIN_SIGNALS, MIN_WIN_RATE, MIN_PF, CHECK_PF = 15, 0.85, 1.0, 1.1
STABLE = {"USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDP", "PYUSD", "USDE", "USD1", "RLUSD", "BFUSD", "XUSD",
          "EUR", "AEUR", "EURI", "GBP", "TRY", "BRL"}
RISK = 0.005


def candidates(info: dict, tickers: list[dict], exclude: set[str], listed_before: str, top: int) -> list[dict]:
    """The `top` USDT perpetuals on a coin by 24h quote volume that traded before `listed_before`."""
    cutoff = pd.Timestamp(listed_before, tz="UTC").timestamp() * 1000
    volume = {t["symbol"]: float(t.get("quoteVolume") or 0) for t in tickers}
    out = []
    for s in info.get("symbols", []):
        if (s.get("contractType") != "PERPETUAL" or s.get("quoteAsset") != "USDT" or s.get("status") != "TRADING"
                or s.get("underlyingType", "COIN") != "COIN" or s.get("baseAsset") in STABLE
                or s["symbol"] in exclude or not s.get("onboardDate") or s["onboardDate"] >= cutoff):
            continue
        out.append({"symbol": s["symbol"], "volume": volume.get(s["symbol"], 0.0),
                    "listed": datetime.fromtimestamp(s["onboardDate"] / 1000, tz=timezone.utc)})
    return sorted(out, key=lambda c: -c["volume"])[:top]


def frame_of(klines, now: datetime) -> pd.DataFrame:
    rows = [{"ts": k.open_time, **{c: getattr(k, c) for c in CANDLE_COLS}} for k in klines if k.is_closed(now)]
    df = pd.DataFrame(rows, columns=["ts", *CANDLE_COLS])
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)


async def download(market: BinanceMarketData, symbols: list[str], start: datetime,
                   end: datetime) -> dict[str, pd.DataFrame]:
    sem = asyncio.Semaphore(4)  # well inside Binance's request weight limits
    frames: dict[str, pd.DataFrame] = {}

    async def one(sym: str) -> None:
        async with sem:
            frames[sym] = frame_of(await market.klines_range(sym, "4h", start, end), end)

    await asyncio.gather(*(one(s) for s in symbols))
    return frames


def trades_frame(trades, session: Session) -> pd.DataFrame:
    rows = []
    for t in trades:
        st = t.state
        if not st.closed:
            continue
        risk_end = st.fills[0][0] if st.fills else st.exit_at
        rows.append({"symbol": t.candidate.symbol, "strategy": t.candidate.strategy, "side": st.side,
                     "entry": pd.Timestamp(st.entry_at), "exit": pd.Timestamp(st.exit_at),
                     "risk_end": pd.Timestamp(risk_end), "net": t.result["net"], "r": t.result["r"],
                     "session": session.contains(st.entry_at)})
    return pd.DataFrame(rows, columns=["symbol", "strategy", "side", "entry", "exit", "risk_end", "net", "r",
                                       "session"])


def kpis(d: pd.DataFrame, days: float) -> dict:
    if d.empty:
        return {"n": 0, "per_day": 0.0, "wr": None, "pf": None, "net": None, "dd": None}
    w, lo = d.net[d.net > 0].sum(), -d.net[d.net <= 0].sum()
    eq = np.cumprod(1 + d.sort_values("exit").r.to_numpy() * RISK)
    return {"n": len(d), "per_day": len(d) / days, "wr": (d.net > 0).mean(), "pf": (w / lo) if lo > 0 else None,
            "net": d.net.mean(), "dd": float((1 - eq / np.maximum.accumulate(eq)).max())}


def fmt_k(k: dict) -> str:
    if not k["n"]:
        return "no signals"
    pf = "∞" if k["pf"] is None else f"{k['pf']:.2f}"
    return (f"{k['n']:>4} signals ({k['per_day']:.2f}/day) · win {k['wr'] * 100:5.1f}% · PF {pf:>4} · "
            f"net {k['net'] * 100:+.2f}%/signal · max fall {k['dd'] * 100:.1f}%")


def cells(k: dict, width: int) -> str:
    """'  n   win    PF' columns of the per-coin table."""
    if not k["n"]:
        return f"{0:>{width}}{'—':>7}{'—':>6}"
    pf = "∞" if k["pf"] is None else f"{k['pf']:.2f}"
    return f"{k['n']:>{width}}{k['wr'] * 100:>6.1f}%{pf:>6}"


def concentration(d: pd.DataFrame) -> tuple[int, float]:
    """Most signals before TP1 in one direction at any 4H check, and the 99th percentile."""
    if d.empty:
        return 0, 0.0
    grid = pd.date_range(d.entry.min().floor("4h"), d.exit.max(), freq="4h").to_numpy()
    ent, end, side = d.entry.to_numpy(), d.risk_end.to_numpy(), d.side.to_numpy()
    same = []
    for g in grid:
        live = (ent <= g) & (end > g)
        same.append(max((live & (side == 1)).sum(), (live & (side == -1)).sum()))
    return int(max(same)), float(np.percentile(same, 99))


async def run(settings: Settings, top: int = 30, listed_before: str = LISTED_BEFORE, start: str = START,
              split: str = SPLIT, now: datetime | None = None, market: BinanceMarketData | None = None,
              say=print) -> dict:
    now = now or datetime.now(timezone.utc)
    market = market or BinanceMarketData([u.strip() for u in settings.binance_futures_urls.split(",") if u.strip()],
                                         "futures")
    current = settings.symbols
    say(f"Coin study · strategies A and B · 4H Binance USDT futures · {start} → {now:%Y-%m-%d}")
    picked = candidates(await market.exchange_info(), await market.tickers_24h(), set(current), listed_before, top)
    say(f"Candidates: top {len(picked)} by 24h volume, on futures before {listed_before}, not in the current "
        f"{len(current)}")
    symbols = sorted(set(current) | {"BTCUSDT"} | {c["symbol"] for c in picked})
    t0 = pd.Timestamp(start, tz="UTC")
    say(f"Downloading 4H candles for {len(symbols)} markets …")
    frames = await download(market, symbols, (t0 - WARMUP).to_pydatetime(), now)
    frames = {s: f for s, f in frames.items() if not f.empty}
    say(f"  {len(frames)} markets, {sum(len(f) for f in frames.values()):,} candles")
    if "BTCUSDT" not in frames:
        raise SystemExit("no BTCUSDT candles: the market regime cannot be computed")
    say("Replaying strategies A and B …")
    costs = Costs(settings.cost_entry, settings.cost_tp, settings.cost_exit)
    trades = await asyncio.to_thread(replay, frames, [s for s in symbols if s in frames], {RGP.code, RSR.code},
                                     None, t0, pd.Timestamp(now), costs)
    d = trades_frame(trades, Session.from_settings(settings))
    ts = pd.Timestamp(split, tz="UTC")
    sel_days, chk_days = (ts - t0).days, max(1, (pd.Timestamp(now) - ts).days)
    sel, chk = d[d.entry < ts], d[d.entry >= ts]

    say("")
    sel_label, chk_label = f"{start[:4]}–{int(split[:4]) - 1} n", f"{split[:4]}– n"
    say(f"{'coin':<14}{'24h vol':>9}{'listed':>9}  {sel_label:>11}{'win':>7}{'PF':>6}  {chk_label:>9}{'win':>7}"
        f"{'PF':>6}  pass")
    rows, passing = [], []
    for c in picked:
        s = c["symbol"]
        a, b = kpis(sel[sel.symbol == s], sel_days), kpis(chk[chk.symbol == s], chk_days)
        ok = (s in frames and a["n"] >= MIN_SIGNALS and a["wr"] >= MIN_WIN_RATE
              and (a["pf"] is None or a["pf"] >= MIN_PF))
        if ok:
            passing.append(s)
        say(f"{s:<14}{c['volume'] / 1e6:>8.0f}M{c['listed'].strftime('%Y-%m'):>9}  {cells(a, 11)}  {cells(b, 9)}  "
            f"{'yes' if ok else 'no'}")
        rows.append({**c, "selection": a, "check": b, "pass": ok})

    say("")
    say(f"Check window {split} → {now:%Y-%m-%d} ({chk_days} days), published signals only (session "
        f"{settings.session_start}–{settings.session_end}):")
    pub = chk[chk.session]
    baskets = {
        f"Current {len(current)} coins (A+B)": pub[pub.symbol.isin(current)],
        f"All {len(picked)} candidates (A+B)": pub[pub.symbol.isin([c['symbol'] for c in picked])],
        f"Passing {len(passing)} coins (A+B)": pub[pub.symbol.isin(passing)],
    }
    summary = {name: kpis(b, chk_days) for name, b in baskets.items()}
    for name, k in summary.items():
        say(f"  {name:<32} {fmt_k(k)}")
    combined = pub[pub.symbol.isin(set(current) | set(passing))]
    most, p99 = concentration(combined)
    say(f"  Same direction before TP1 (A+B, current + passing): max {most}, 99th percentile {p99:.0f}")

    k = summary[f"Passing {len(passing)} coins (A+B)"]
    good = bool(passing) and k["n"] >= 30 and k["wr"] >= MIN_WIN_RATE and (k["pf"] is None or k["pf"] >= CHECK_PF)
    say("")
    if good:
        say(f"VERDICT: ADD the {len(passing)} passing coins: they held up in the check window. Expected extra "
            f"published signals: about {k['per_day']:.1f} a day (strategy C stays on its {len(current)} coins).")
        say("Suggested UNIVERSE (review before use):")
        say("UNIVERSE=" + ",".join(current + passing))
    else:
        say("VERDICT: DO NOT ADD: the passing coins did not hold up in the check window (or too few passed).")
    return {"candidates": rows, "passing": passing, "baskets": summary, "concentration": (most, p99),
            "recommend": good}
