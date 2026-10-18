"""Public, read-only API used by the dashboard."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import __version__
from ..config import Settings, get_settings
from ..core import stats
from ..core.catalog import BAR_SECONDS, BOOK_BENCHMARK, INTERVAL, STRATEGIES
from ..core.session import Session
from ..db import get_session
from ..market.base import floor_time
from ..models import Candle, Signal
from ..services import repo
from .serialize import CSV_COLUMNS, kpis_out, signal_out

router = APIRouter(prefix="/api")

Origin = Literal["default", "live", "demo", "backfill", "all"]


def origin_filter(origin: str):
    if origin == "all":
        return None
    if origin == "default":  # everything the engine produced in real (or demo) time
        return Signal.origin.in_(["live", "demo"])
    return Signal.origin == origin


def heartbeat_alive(hb: dict | None) -> tuple[bool, float | None]:
    if not hb or not hb.get("at"):
        return False, None
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(hb["at"])).total_seconds()
    return age < 90, age


@router.get("/meta")
async def meta(s: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)):
    states = await repo.strategy_states(s)
    hb = await repo.get_state(s, "heartbeat") or {}
    tg = await repo.get_state(s, "telegram") or {}
    last_eval = await repo.get_state(s, "last_eval") or {}
    alive, age = heartbeat_alive(hb)
    clock = datetime.fromisoformat(hb["clock"]) if hb.get("clock") else datetime.now(timezone.utc)
    next_close = floor_time(clock, INTERVAL) + timedelta(seconds=BAR_SECONDS)
    ses = Session.from_settings(settings)
    next_check = next_close
    while not ses.contains(next_check):  # the next 4H close that publishes
        next_check += timedelta(seconds=BAR_SECONDS)
    strategies = []
    for code, spec in STRATEGIES.items():
        st = states.get(code)
        strategies.append({
            "code": code, "letter": spec.letter, "name": spec.name, "kind": spec.kind,
            "summary": spec.summary, "rules": spec.rules, "tp_atr": spec.tp_atr, "sl_atr": spec.sl_atr,
            "max_bars": spec.max_bars, "targets_atr": list(spec.targets_atr),
            "target_sizes": list(spec.target_sizes), "breakeven": spec.breakeven, "benchmark": spec.benchmark,
            "mode": st.mode if st else None, "auto_paused": bool(st and st.auto_paused),
            "pause_reason": st.pause_reason if st else None,
        })
    return {
        "app_name": settings.app_name, "version": __version__, "environment": settings.environment,
        "demo": settings.is_replay or bool(hb.get("simulated")),
        "source": hb.get("source", settings.market_data_source),
        "universe": settings.symbols, "interval": INTERVAL, "strategies": strategies,
        "book_benchmark": BOOK_BENCHMARK,
        "model": {"version": hb.get("model"), "threshold": hb.get("model_threshold")} if hb.get("model") else None,
        "telegram": {"enabled": settings.telegram_enabled, "channel_url": settings.telegram_channel_url,
                     "bot_username": tg.get("bot")},
        "default_risk_pct": settings.default_risk_pct,
        "session": {"tz": settings.session_tz, "tz_abbr": ses.tzname(clock), "start": settings.session_start,
                    "end": settings.session_end, "open": ses.contains(clock), "next_open": ses.next_start(clock),
                    "next_close": ses.next_end(clock), "next_check": next_check,
                    "checks": [ses.label(t, with_date=False) for t in ses.checks(ses.local(clock).date())]},
        "costs": {"entry": settings.cost_entry, "tp": settings.cost_tp, "exit": settings.cost_exit},
        "server_time": datetime.now(timezone.utc), "clock": clock, "next_candle_close": next_close,
        "last_eval": last_eval, "engine": {"alive": alive, "heartbeat_age_s": age},
    }


def signal_query(status: str, strategy: str | None, symbol: str | None, side: str | None,
                 outcome: str | None, origin: str, since: datetime | None, until: datetime | None):
    conds = [Signal.published.is_(True)]
    if status == "active":
        conds.append(Signal.status == "ACTIVE")
    elif status == "closed":
        conds.append(Signal.status == "CLOSED")
    if strategy:
        conds.append(Signal.strategy == strategy.upper())
    if symbol:
        conds.append(Signal.symbol == symbol.upper())
    if side:
        conds.append(Signal.side == (1 if side.lower() == "long" else -1))
    if outcome:
        conds.append(Signal.exit_reason == outcome.upper())
    of = origin_filter(origin)
    if of is not None:
        conds.append(of)
    if since:
        conds.append(Signal.entry_at >= since)
    if until:
        conds.append(Signal.entry_at < until)
    return and_(*conds)


@router.get("/signals")
async def list_signals(status: Literal["active", "closed", "all"] = "all", strategy: str | None = None,
                       symbol: str | None = None, side: Literal["long", "short"] | None = None,
                       outcome: Literal["TP", "SL", "BE", "TIME"] | None = None, origin: Origin = "default",
                       since: datetime | None = None, until: datetime | None = None,
                       limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
                       s: AsyncSession = Depends(get_session)):
    where = signal_query(status, strategy, symbol, side, outcome, origin, since, until)
    total = await s.scalar(select(func.count()).select_from(Signal).where(where))
    order = Signal.entry_at.desc() if status != "closed" else Signal.exit_at.desc()
    rows = (await s.scalars(select(Signal).where(where).order_by(order, Signal.id.desc())
                            .limit(limit).offset(offset))).all()
    return {"total": total, "items": [signal_out(r) for r in rows]}


@router.get("/signals.csv")
async def export_signals(status: Literal["active", "closed", "all"] = "all", strategy: str | None = None,
                         symbol: str | None = None, side: Literal["long", "short"] | None = None,
                         outcome: Literal["TP", "SL", "BE", "TIME"] | None = None, origin: Origin = "default",
                         since: datetime | None = None, until: datetime | None = None,
                         s: AsyncSession = Depends(get_session)):
    where = signal_query(status, strategy, symbol, side, outcome, origin, since, until)
    rows = (await s.scalars(select(Signal).where(where).order_by(Signal.entry_at))).all()
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(signal_out(r))
    name = f"signals-{datetime.now(timezone.utc):%Y%m%d-%H%M}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/signals/{signal_id}")
async def get_signal(signal_id: int, s: AsyncSession = Depends(get_session)):
    row = await s.get(Signal, signal_id)
    if row is None or not row.published:
        raise HTTPException(404, "signal not found")
    return signal_out(row)


async def closed_rows(s: AsyncSession, strategy: str | None, origin: str, since: datetime | None):
    conds = [Signal.status == "CLOSED", Signal.published.is_(True)]
    if strategy and strategy.upper() != "ALL":
        conds.append(Signal.strategy == strategy.upper())
    of = origin_filter(origin)
    if of is not None:
        conds.append(of)
    if since:
        conds.append(Signal.exit_at >= since)
    rows = (await s.execute(select(Signal.strategy, Signal.exit_at, Signal.entry_at, Signal.pnl_net,
                                   Signal.r_multiple, Signal.exit_reason, Signal.targets_hit).where(and_(*conds))
                            .order_by(Signal.exit_at))).all()
    return [r._asdict() for r in rows]


async def window_start(s: AsyncSession, days: int | None) -> datetime | None:
    if not days:
        return None
    hb = await repo.get_state(s, "heartbeat") or {}
    now = datetime.fromisoformat(hb["clock"]) if hb.get("clock") else datetime.now(timezone.utc)
    return now - timedelta(days=days)


@router.get("/stats")
async def get_stats(strategy: str = "ALL", days: int | None = Query(None, ge=1, le=3650),
                    origin: Origin = "default", s: AsyncSession = Depends(get_session)):
    since = await window_start(s, days)
    rows = await closed_rows(s, None, origin, since)
    first = rows[0]["entry_at"] if rows else None
    span = days or (max(1.0, (rows[-1]["exit_at"] - first).total_seconds() / 86400) if rows else None)
    def pick(code: str) -> list[dict]:
        return [r for r in rows if r["strategy"] == code]

    sel = rows if strategy.upper() == "ALL" else pick(strategy.upper())
    open_count = await s.scalar(select(func.count()).select_from(Signal).where(
        Signal.status == "ACTIVE", Signal.published.is_(True)))
    return {
        "strategy": strategy.upper(), "days": days, "origin": origin, "since": since, "first_entry_at": first,
        "open_signals": open_count,
        "kpis": kpis_out(stats.kpis(sel, span)),
        "by_strategy": {code: kpis_out(stats.kpis(pick(code), span)) for code in STRATEGIES},
        "benchmark": BOOK_BENCHMARK if strategy.upper() == "ALL" else STRATEGIES[strategy.upper()].benchmark,
    }


@router.get("/stats/equity")
async def get_equity(strategy: str = "ALL", risk: float = Query(0.5, gt=0, le=5),
                     days: int | None = Query(None, ge=1, le=3650), origin: Origin = "default",
                     s: AsyncSession = Depends(get_session)):
    rows = await closed_rows(s, strategy, origin, await window_start(s, days))
    curve = stats.equity_curve(rows, risk / 100)
    return {"strategy": strategy.upper(), "risk_pct": risk, "total_return_pct": curve["total_return"] * 100,
            "max_drawdown_pct": curve["max_drawdown"] * 100,
            "points": [{"t": p["t"], "equity": p["equity"], "drawdown_pct": p["drawdown"] * 100}
                       for p in curve["points"]]}


@router.get("/stats/monthly")
async def get_monthly(strategy: str = "ALL", origin: Origin = "default", s: AsyncSession = Depends(get_session)):
    rows = await closed_rows(s, strategy, origin, None)
    return [{**m, "win_rate": None if m["win_rate"] is None else m["win_rate"] * 100,
             "expectancy": None if m["expectancy"] is None else m["expectancy"] * 100}
            for m in stats.monthly(rows)]


@router.get("/regime")
async def get_regime(s: AsyncSession = Depends(get_session)):
    return {"items": await repo.get_state(s, "regime", {})}


@router.get("/prices")
async def get_prices(s: AsyncSession = Depends(get_session)):
    return await repo.get_state(s, "prices", {"at": None, "prices": {}})


@router.get("/candles")
async def get_candles(symbol: str, limit: int = Query(300, ge=10, le=1500), end: datetime | None = None,
                      s: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)):
    symbol = symbol.upper()
    q = select(Candle).where(Candle.symbol == symbol, Candle.interval == INTERVAL)
    if end:
        q = q.where(Candle.open_time <= end)
    rows = (await s.scalars(q.order_by(desc(Candle.open_time)).limit(limit))).all()[::-1]
    return [{"t": int(r.open_time.timestamp()), "o": r.open, "h": r.high, "l": r.low, "c": r.close,
             "v": r.volume} for r in rows]


@router.get("/health")
async def health(s: AsyncSession = Depends(get_session)):
    await s.execute(select(1))
    alive, age = heartbeat_alive(await repo.get_state(s, "heartbeat"))
    return {"status": "ok", "db": "ok", "engine_alive": alive, "engine_heartbeat_age_s": age}
