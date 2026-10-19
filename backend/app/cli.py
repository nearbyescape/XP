"""Operations CLI.

    python -m app.cli import-candles --dir /data/parquet           # seed 4h history from parquet files
    python -m app.cli backfill-ledger --since 2026-01-01           # replay strategies into the ledger
    python -m app.cli telegram-test [--chat @channel]              # send a test message now
    python -m app.cli status                                       # engine / strategy summary
    python -m app.cli preflight [--send]                           # launch checks (exit 1 on failure)
    python -m app.cli coin-study [--top 30]                        # which extra coins can run A and B
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import func, select

from . import db, log
from .config import get_settings
from .core.catalog import INTERVAL, STRATEGIES
from .core.lifecycle import Costs
from .core.ml import MLModel
from .core.replay import replay
from .market.base import Kline
from .models import Signal
from .services import repo


async def import_candles(directory: str) -> None:
    settings = get_settings()
    model = MLModel.try_load(settings.model_path)
    symbols = sorted(set(settings.symbols) | {"BTCUSDT"} | (set(model.symbols) if model else set()))
    for sym in symbols:
        path = Path(directory) / f"{sym}_{INTERVAL}.parquet"
        if not path.exists():
            print(f"skip {sym}: {path} not found")
            continue
        df = pd.read_parquet(path)
        step = pd.Timedelta(INTERVAL)
        klines = [Kline(r.ts.to_pydatetime(), (r.ts + step).to_pydatetime(), r.open, r.high, r.low, r.close,
                        r.volume, r.quote_volume, int(r.trades), r.taker_buy_base, r.taker_buy_quote)
                  for r in df.itertuples(index=False)]
        async with db.sessions()() as s:
            n = await repo.upsert_candles(s, sym, INTERVAL, klines)
            await s.commit()
        print(f"{sym}: {n} candles ({df.ts.iloc[0]:%Y-%m-%d} → {df.ts.iloc[-1]:%Y-%m-%d})")


async def backfill_ledger(since: str, until: str | None) -> None:
    """Replay the validated strategies over stored candles and record the signals as
    origin=backfill (never published, excluded from live statistics by default)."""
    settings = get_settings()
    model = MLModel.try_load(settings.model_path)
    symbols = sorted(set(settings.symbols) | {"BTCUSDT"} | (set(model.symbols) if model else set()))
    async with db.sessions()() as s:
        frames = {sym: await repo.load_frame(s, sym, INTERVAL) for sym in symbols}
    start = pd.Timestamp(since, tz="UTC")
    end = pd.Timestamp(until, tz="UTC") if until else max(f.ts.iloc[-1] for f in frames.values())
    trades = replay(frames, settings.symbols, set(STRATEGIES), model, start, end,
                    Costs(settings.cost_entry, settings.cost_tp, settings.cost_exit))
    added = 0
    async with db.sessions()() as s:
        for t in trades:
            c, st = t.candidate, t.state
            uid = f"{c.strategy}:{c.symbol}:{c.signal_open:%Y-%m-%dT%H:%MZ}"
            if await s.scalar(select(Signal.id).where(Signal.uid == uid)):
                continue
            row = Signal(
                uid=uid, origin="backfill", strategy=c.strategy, symbol=c.symbol, side=c.side,
                signal_open_at=c.signal_open.to_pydatetime(), entry_at=st.entry_at, expires_at=st.expires_at,
                entry_price=st.entry_price, take_profit=st.take_profit, stop_loss=st.initial_stop,
                targets=[[p, z] for p, z in zip(st.targets, st.sizes, strict=True)], breakeven=st.breakeven,
                atr=c.atr,
                tp_atr=c.tp_atr, sl_atr=c.sl_atr, max_bars=c.max_bars, regime_coin=c.regime_coin,
                regime_btc=c.regime_btc, model_prob=c.model_prob,
                model_version=model.version if (model and c.model_prob is not None) else None,
                mode="backfill", published=False,
                status="CLOSED" if st.closed else "ACTIVE", exit_reason=st.exit_reason,
                exit_price=st.exit_price, exit_at=st.exit_at, pnl_gross=t.result.get("gross"),
                pnl_net=t.result.get("net"), r_multiple=t.result.get("r"),
            )
            repo.store_progress(row, st)
            row.last_price = st.last_price or st.entry_price
            s.add(row)
            added += 1
        await s.commit()
    print(f"backfill ledger: {added} signals written ({start:%Y-%m-%d} → {end:%Y-%m-%d})")


async def telegram_test(chat: str | None) -> None:
    from .telegram.client import TelegramClient

    settings = get_settings()
    if not settings.telegram_enabled:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")
    target = chat or settings.telegram_channel_id
    if not target:
        raise SystemExit("no --chat given and TELEGRAM_CHANNEL_ID is not set")
    client = TelegramClient(settings.telegram_bot_token.get_secret_value(), settings.telegram_api_base)
    me = await client.get_me()
    res = await client.send_message(target, f"✅ <b>{settings.app_name}</b> is connected to "
                                            f"@{me['username']} ({datetime.now(timezone.utc):%d %b %H:%M} UTC)")
    await client.close()
    print(f"sent message {res['message_id']} to {target} as @{me['username']}")


async def status() -> None:
    async with db.sessions()() as s:
        states = await repo.strategy_states(s)
        counts = (await s.execute(select(Signal.strategy, Signal.status, func.count())
                                  .group_by(Signal.strategy, Signal.status))).all()
        out = {
            "heartbeat": await repo.get_state(s, "heartbeat"),
            "last_eval": await repo.get_state(s, "last_eval"),
            "strategies": {c: {"mode": st.mode, "auto_paused": st.auto_paused} for c, st in states.items()},
            "signals": [{"strategy": a, "status": b, "count": n} for a, b, n in counts],
        }
    print(json.dumps(out, indent=2, default=str))


async def preflight(send: bool) -> None:
    from . import preflight as pf

    code = pf.report(await pf.run(get_settings(), send=send))
    if code:
        raise SystemExit(code)


async def coin_study(top: int, listed_before: str) -> None:
    from . import coinstudy

    await coinstudy.run(get_settings(), top=top, listed_before=listed_before)


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("import-candles")
    p.add_argument("--dir", required=True)
    p = sub.add_parser("backfill-ledger")
    p.add_argument("--since", required=True)
    p.add_argument("--until")
    p = sub.add_parser("telegram-test")
    p.add_argument("--chat")
    sub.add_parser("status")
    p = sub.add_parser("preflight", help="check config, database, model, Binance and Telegram before launch")
    p.add_argument("--send", action="store_true", help="also send a test message to each admin chat")
    p = sub.add_parser("coin-study", help="replay strategies A and B on more Binance futures coins (read-only)")
    p.add_argument("--top", type=int, default=30)
    p.add_argument("--listed-before", default="2023-01-01")
    sub.add_parser("create-tables", help="SQLite/dev only; production uses `alembic upgrade head`")
    args = ap.parse_args()

    settings = get_settings()
    log.setup(settings.log_level)
    db.configure(settings.database_url)
    coro = {
        "import-candles": lambda: import_candles(args.dir),
        "backfill-ledger": lambda: backfill_ledger(args.since, args.until),
        "telegram-test": lambda: telegram_test(args.chat),
        "status": status,
        "preflight": lambda: preflight(args.send),
        "coin-study": lambda: coin_study(args.top, args.listed_before),
        "create-tables": db.create_all,
    }[args.cmd]()
    asyncio.run(coro)


if __name__ == "__main__":
    main()
