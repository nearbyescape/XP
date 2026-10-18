"""The signal engine process.

Loops (all asyncio, one process):
  candles  - at every 4h close (+ delay): sync candles, evaluate A/B/C, open signals, notify
  tracker  - every minute: walk open signals through closed 1m candles (TP / SL / time exits)
  prices   - every 15 s: last prices for the dashboard
  heartbeat- every 15 s: liveness for the API / admin console
  telegram - outbox sender, bot commands (long polling), session greeting and summary
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import select

from .. import __version__, db
from ..config import Settings
from ..core.catalog import BAR_SECONDS, INTERVAL, STRATEGIES
from ..core.evaluate import Candidate, evaluate_candle, regime_snapshot
from ..core.lifecycle import Bar, Costs, pnl, step
from ..core.ml import MLModel
from ..core.replay import new_trade
from ..core.session import Session
from ..market.base import MarketData, floor_time
from ..models import Signal, utcnow
from ..services import repo
from ..telegram import formatting as fmt
from ..telegram.service import TelegramService
from .clock import Clock
from .killswitch import review_strategy

log = logging.getLogger(__name__)
BAR = timedelta(seconds=BAR_SECONDS)
MARKET_DOWN_ALERT_SECONDS = 300
ALIVE_FILE = "/tmp/engine.alive"  # touched by the heartbeat; read by the container healthcheck


class Engine:
    def __init__(self, settings: Settings, market: MarketData, clock: Clock,
                 model: MLModel | None, telegram: TelegramService | None = None):
        self.settings = settings
        self.market = market
        self.clock = clock
        self.model = model
        self.telegram = telegram
        self.costs = Costs(settings.cost_entry, settings.cost_tp, settings.cost_exit)
        self.symbols = settings.symbols
        needed = set(self.symbols) | {"BTCUSDT"} | (set(model.symbols) if model else set())
        self.data_symbols = sorted(needed)
        self.frames: dict[str, pd.DataFrame] = {}
        self.current_open: dict[str, tuple[datetime, float]] = {}
        self.origin = "demo" if clock.simulated else "live"
        self.session = Session.from_settings(settings)
        self._tracking = asyncio.Lock()  # the tracker loop and candle evaluation must not overlap
        self.started = time.time()

    # ------------------------------------------------------------------ bootstrap
    async def bootstrap(self) -> None:
        async with db.sessions()() as s:
            await repo.ensure_strategy_states(s, {c: self.settings.modes.get(c, "live") for c in STRATEGIES})
            last_eval = await repo.get_state(s, "last_eval", {})
        if self.clock.simulated and last_eval.get("candle"):
            resume = pd.Timestamp(last_eval["candle"]).to_pydatetime() + BAR
            if resume > self.clock.now():
                self.clock.jump_to(resume)  # demo restarted: continue where it stopped
        await self.event("info", "engine.start",
                         f"engine {__version__} started ({self.market.name}, origin={self.origin})",
                         {"symbols": self.symbols, "model": self.model.version if self.model else None},
                         alert=True)
        for sym in self.data_symbols:
            await self.backfill(sym)
        now = pd.Timestamp(self.clock.now())
        async with db.sessions()() as s:
            for sym in self.data_symbols:
                f = await repo.load_frame(s, sym, INTERVAL)
                # only candles that have closed by now (a demo clock may start before stored data ends)
                self.frames[sym] = f[f.ts + pd.Timedelta(seconds=BAR_SECONDS) <= now].reset_index(drop=True)
            await repo.set_state(s, "regime", regime_snapshot({k: self.frames[k] for k in self.symbols
                                                               if k in self.frames}))
            await s.commit()
        log.info("bootstrap complete: %s", {k: len(v) for k, v in self.frames.items()})

    async def backfill(self, sym: str) -> None:
        now = self.clock.now()
        async with db.sessions()() as s:
            last = await repo.latest_candle_time(s, sym, INTERVAL)
        start = (last - BAR) if last else self.settings.backfill_from
        klines = await self.market.klines_range(sym, INTERVAL, start, now)
        closed = [k for k in klines if k.is_closed(now)]
        async with db.sessions()() as s:
            n = await repo.upsert_candles(s, sym, INTERVAL, closed)
            await s.commit()
        log.info("backfill %s: %d candles from %s", sym, n, start.date())

    # ------------------------------------------------------------------ candles
    async def sync_candles(self, since: datetime) -> None:
        now = self.clock.now()
        for sym in self.data_symbols:
            try:
                kl = await self.market.klines(sym, INTERVAL, start=since, limit=50)
            except Exception as exc:  # noqa: BLE001 - one coin failing must not stop the others
                log.error("candle sync failed for %s: %s", sym, exc)
                continue
            closed = [k for k in kl if k.is_closed(now)]
            for k in kl:
                if not k.is_closed(now):
                    self.current_open[sym] = (k.open_time, k.open)
            if not closed:
                continue
            async with db.sessions()() as s:
                await repo.upsert_candles(s, sym, INTERVAL, closed)
                await s.commit()
            new = pd.DataFrame([{"ts": k.open_time, **{c: getattr(k, c) for c in repo.CANDLE_COLS}}
                                for k in closed])
            new["ts"] = pd.to_datetime(new["ts"], utc=True)
            old = self.frames.get(sym, pd.DataFrame(columns=new.columns))
            frame = pd.concat([old[old.ts < new.ts.min()], new], ignore_index=True) if len(old) else new
            self.frames[sym] = frame.drop_duplicates("ts", keep="last").sort_values("ts").reset_index(drop=True)

    async def candle_loop(self) -> None:
        while True:
            try:
                wake = await self.candle_tick()
            except Exception as exc:  # noqa: BLE001 - e.g. the database is unreachable: retry, don't exit
                log.exception("candle loop error")
                await self.safe(self.event("error", "candle.error", f"candle: {exc.__class__.__name__}: {exc}"),
                                "candle")
                await self.clock.sleep(30)
                continue
            await self.clock.sleep_until(wake)

    async def candle_tick(self) -> datetime:
        """Evaluate every closed candle not evaluated yet; returns when to wake up next."""
        now = self.clock.now()
        current = floor_time(now, INTERVAL)
        target = current - BAR  # the most recently closed candle
        async with db.sessions()() as s:
            last_eval = await repo.get_state(s, "last_eval", {})
        last_t = pd.Timestamp(last_eval["candle"]) if last_eval.get("candle") else None
        if last_t is None or last_t < pd.Timestamp(target):
            lag = now - current
            if self.clock.simulated:
                # the demo clock keeps running while we compute: catch up candle by candle
                t = pd.Timestamp(target) if last_t is None else last_t + pd.Timedelta(BAR)
                while t <= pd.Timestamp(target):
                    await self.safe(self.process_candle(t), "candle")
                    t += pd.Timedelta(BAR)
            elif lag <= timedelta(minutes=self.settings.max_signal_latency_minutes):
                await self.safe(self.process_candle(pd.Timestamp(target)), "candle")
            else:
                await self.event("warning", "candle.skipped",
                                 f"skipped evaluation of {target:%Y-%m-%d %H:%M} (engine was {lag} late)")
                await self.set_last_eval(pd.Timestamp(target), skipped=True)
        return current + BAR + timedelta(seconds=self.settings.eval_delay_seconds)

    async def process_candle(self, t: pd.Timestamp) -> None:
        started = time.monotonic()
        for attempt in range(4):
            await self.sync_candles(t.to_pydatetime() - 2 * BAR)
            missing = [s for s in self.data_symbols
                       if s not in self.frames or self.frames[s].empty or not (self.frames[s].ts == t).any()]
            if not missing:
                break
            log.warning("candle %s missing for %s (attempt %d)", t, missing, attempt + 1)
            await self.clock.sleep(10)
        else:
            await self.event("warning", "candle.incomplete",
                             f"{t:%Y-%m-%d %H:%M} candle still missing for {', '.join(missing)} after retries; "
                             f"evaluated without them")
        # exits inside the candle that just closed must free their coin before we evaluate it
        await self.track_once(until=(t + pd.Timedelta(BAR)).to_pydatetime())
        close_t = (t + pd.Timedelta(BAR)).to_pydatetime()
        async with db.sessions()() as s:
            states = await repo.strategy_states(s)
            open_positions = await repo.positions_open_at(s, close_t)
        enabled = {c for c, st in states.items() if st.mode != "off"}
        frames = {k: v[v.ts <= t] for k, v in self.frames.items() if not v.empty}
        cands = await asyncio.to_thread(evaluate_candle, frames, t, self.symbols, open_positions,
                                        enabled, self.model)
        created = []
        for c in cands:
            sig = await self.open_signal(c, states[c.strategy])
            if sig:
                created.append(sig)
        async with db.sessions()() as s:
            await repo.set_state(s, "regime", regime_snapshot({k: frames[k] for k in self.symbols if k in frames}))
            await s.commit()
        await self.set_last_eval(t, signals=len(created), seconds=round(time.monotonic() - started, 2))
        await self.event("info", "candle.evaluated",
                         f"{t:%Y-%m-%d %H:%M} evaluated: {len(created)} new signal(s)",
                         {"signals": [s.uid for s in created]})

    async def open_signal(self, c: Candidate, state) -> Signal | None:
        entry_at = (c.signal_open + pd.Timedelta(seconds=BAR_SECONDS)).to_pydatetime()
        cur = self.current_open.get(c.symbol)
        if not cur or cur[0] != entry_at:
            kl = await self.market.klines(c.symbol, INTERVAL, start=entry_at, limit=1)
            if not kl or kl[0].open_time != entry_at:
                log.error("no entry candle for %s %s", c.strategy, c.symbol)
                return None
            cur = (kl[0].open_time, kl[0].open)
        entry = float(cur[1])
        st = new_trade(c, entry, entry_at)
        # publish only signals whose candle closes inside the session; the others are tracked
        in_session = self.session.contains(entry_at)
        published = state.mode == "live" and not state.auto_paused and in_session
        uid = f"{c.strategy}:{c.symbol}:{c.signal_open:%Y-%m-%dT%H:%MZ}"
        async with db.sessions()() as s:
            if await s.scalar(select(Signal.id).where(Signal.uid == uid)):
                return None  # idempotent: already created (restart during the same candle)
            sig = Signal(
                uid=uid, origin=self.origin, strategy=c.strategy, symbol=c.symbol, side=c.side,
                signal_open_at=c.signal_open.to_pydatetime(), entry_at=entry_at,
                expires_at=st.expires_at, entry_price=entry, take_profit=st.take_profit, stop_loss=st.stop_loss,
                targets=[[p, z] for p, z in zip(st.targets, st.sizes, strict=True)], breakeven=st.breakeven,
                stop_current=st.stop_loss, fills=[], targets_hit=0,
                atr=c.atr, tp_atr=c.tp_atr, sl_atr=c.sl_atr, max_bars=c.max_bars,
                regime_coin=c.regime_coin, regime_btc=c.regime_btc, model_prob=c.model_prob,
                model_version=self.model.version if (c.model_prob is not None and self.model) else None,
                mode="live" if published else ("shadow" if state.mode != "live"
                                               else "paused" if state.auto_paused else "offhours"),
                published=published, status="ACTIVE", last_price=entry, mfe=0.0, mae=0.0,
            )
            s.add(sig)
            await s.flush()
            if self.telegram:
                await self.telegram.enqueue_signal_new(s, sig)
            await repo.log_event(s, "info", "signal.new",
                                 f"{c.strategy} {'LONG' if c.side == 1 else 'SHORT'} {c.symbol} @ {entry:g}"
                                 + ("" if published else f" ({sig.mode}, not published)"),
                                 {"signal_id": sig.id, "prob": c.model_prob})
            await s.commit()
            return sig

    # ------------------------------------------------------------------ tracker
    async def tracker_loop(self) -> None:
        interval = self.settings.tracker_interval_seconds
        if self.clock.simulated:
            interval = max(interval, 900)  # replay tracks on 15m candles
        while True:
            await self.safe(self.track_once(), "tracker")
            await self.clock.sleep(interval)

    async def track_once(self, until: datetime | None = None) -> None:
        async with self._tracking:
            await self._track(until)

    async def _track(self, until: datetime | None) -> None:
        async with db.sessions()() as s:
            rows = await repo.open_signals(s)
        if not rows:
            return
        now = min(self.clock.now(), until) if until else self.clock.now()
        fine = self.market.fine_interval
        by_symbol: dict[str, list[Signal]] = {}
        for r in rows:
            by_symbol.setdefault(r.symbol, []).append(r)
        for sym, sigs in by_symbol.items():
            since = min((r.last_checked_at or r.entry_at) for r in sigs)
            try:
                bars = [k for k in await self.market.klines_range(sym, fine, floor_time(since, fine), now)
                        if k.is_closed(now)]
            except Exception as exc:  # noqa: BLE001
                log.error("tracker: %s %s candles failed: %s", sym, fine, exc)
                continue
            for sig in sigs:
                await self.advance(sig, [Bar(k.open_time, k.close_time, k.open, k.high, k.low, k.close)
                                         for k in bars])

    async def advance(self, sig: Signal, bars: list[Bar]) -> None:
        st = repo.trade_state(sig)
        hit_before = st.targets_hit
        for b in bars:
            if step(st, b):
                break
        if st.last_checked_at == sig.last_checked_at and not st.closed:
            return
        async with db.sessions()() as s:
            row = await s.get(Signal, sig.id)
            if row is None or row.status != "ACTIVE":
                return
            if row.last_checked_at and st.last_checked_at and row.last_checked_at >= st.last_checked_at:
                return  # another pass already advanced this signal from fresher state
            repo.store_progress(row, st)
            row.updated_at = utcnow()
            if st.closed:
                res = pnl(st, self.costs)
                row.status, row.exit_reason = "CLOSED", st.exit_reason
                row.exit_price, row.exit_at = st.exit_price, st.exit_at
                row.pnl_gross, row.pnl_net, row.r_multiple = res["gross"], res["net"], res["r"]
                await repo.log_event(s, "info", "signal.closed",
                                     f"{row.strategy} {row.symbol} {st.exit_reason} net {res['net'] * 100:+.2f}% "
                                     f"({res['r']:+.2f}R)", {"signal_id": row.id})
                if self.telegram:
                    await self.telegram.enqueue_signal_close(s, row, hit_before)
                await s.commit()
                await review_strategy(s, row.strategy, self.settings, self.telegram, self.clock.now())
                await s.commit()
            elif st.targets_hit > hit_before:
                await repo.log_event(s, "info", "signal.target",
                                     f"{row.strategy} {row.symbol} TP{st.targets_hit} hit"
                                     + (" · stop moved to entry" if hit_before == 0 and row.breakeven else ""),
                                     {"signal_id": row.id})
                if self.telegram:
                    await self.telegram.enqueue_signal_update(s, row, hit_before)
                await s.commit()
            else:
                await s.commit()

    # ------------------------------------------------------------------ prices / heartbeat
    async def price_loop(self) -> None:
        """Last prices for the dashboard; doubles as the market-data outage detector."""
        interval = self.settings.price_interval_seconds if not self.clock.simulated else 900
        down_since: float | None = None
        alerted = False
        while True:
            try:
                prices = await self.market.prices(self.symbols)
            except Exception as exc:  # noqa: BLE001
                log.warning("price refresh failed: %s", exc)
                if down_since is None:
                    down_since = time.monotonic()
                down_for = time.monotonic() - down_since
                if not alerted and down_for >= MARKET_DOWN_ALERT_SECONDS:
                    alerted = True
                    await self.safe(self.event("error", "market.down",
                                               f"{self.market.name} unreachable for {fmt.duration(down_for)}: "
                                               f"{exc.__class__.__name__}: {exc}"), "prices")
            else:
                if alerted:
                    await self.safe(self.event("info", "market.recovered",
                                               f"{self.market.name} reachable again after "
                                               f"{fmt.duration(time.monotonic() - down_since)}", alert=True),
                                    "prices")
                down_since, alerted = None, False
                await self.safe(self.store_prices(prices), "prices")
            await self.clock.sleep(interval)

    async def store_prices(self, prices: dict) -> None:
        async with db.sessions()() as s:
            await repo.set_state(s, "prices", {"at": self.clock.now().isoformat(), "prices": prices})
            await s.commit()

    async def heartbeat_loop(self) -> None:
        while True:
            try:
                async with db.sessions()() as s:
                    tg = await self.telegram.queue_health(s) if self.telegram else None
                    await repo.set_state(s, "heartbeat", {
                        "at": utcnow().isoformat(), "clock": self.clock.now().isoformat(),
                        "simulated": self.clock.simulated, "source": self.market.name,
                        "fine_interval": self.market.fine_interval, "version": __version__,
                        "model": self.model.version if self.model else None,
                        "model_threshold": self.model.threshold if self.model else None,
                        "uptime_s": int(time.time() - self.started), "telegram_queue": tg,
                        "telegram_enabled": bool(self.telegram and self.telegram.enabled),
                        "candles": {k: str(v.ts.iloc[-1]) for k, v in self.frames.items() if len(v)},
                    })
                    await s.commit()
                Path(ALIVE_FILE).touch()
            except Exception:  # noqa: BLE001
                log.exception("heartbeat failed")
            await asyncio.sleep(15)

    # ------------------------------------------------------------------ helpers
    async def set_last_eval(self, t: pd.Timestamp, **extra) -> None:
        async with db.sessions()() as s:
            await repo.set_state(s, "last_eval", {"candle": t.isoformat(), "at": utcnow().isoformat(), **extra})
            await s.commit()

    async def event(self, level: str, kind: str, message: str, data: dict | None = None,
                    alert: bool | None = None) -> None:
        """Record an engine event. Warnings and errors also alert the admin chats (throttled per kind)."""
        log.log({"warning": logging.WARNING, "error": logging.ERROR}.get(level, logging.INFO), message)
        async with db.sessions()() as s:
            await repo.log_event(s, level, kind, message, data)
            if self.telegram and (level in ("warning", "error") if alert is None else alert):
                await self.telegram.enqueue_admin(s, fmt.alert(self.settings.app_name, level, kind, message),
                                                  key=kind)
            await s.commit()

    async def safe(self, coro, name: str) -> None:
        try:
            await coro
        except Exception as exc:  # noqa: BLE001 - loops must survive; the failure is recorded
            log.exception("%s loop error", name)
            try:
                await self.event("error", f"{name}.error", f"{name}: {exc.__class__.__name__}: {exc}")
            except Exception:  # noqa: BLE001
                pass

    async def run(self) -> None:
        await self.bootstrap()
        tasks = [self.candle_loop(), self.tracker_loop(), self.price_loop(), self.heartbeat_loop()]
        if self.telegram and self.telegram.enabled:
            tasks += [self.telegram.sender_loop(), self.telegram.updates_loop()]
            if self.settings.telegram_session_messages:
                tasks.append(self.telegram.session_loop())
        await asyncio.gather(*tasks)
