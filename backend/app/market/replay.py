"""Historical replay source: serves stored parquet candles "as of" a simulated clock.

Demo / staging only. The engine runs unchanged; it just sees the past through this source.
Candles that have not closed yet at the simulated time are returned as an in-progress candle
holding only the open price (no future high/low/close leaks into the engine).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from ..engine.clock import Clock
from .base import Kline, interval_seconds

log = logging.getLogger(__name__)


class ReplayMarketData:
    name = "replay"

    def __init__(self, data_dir: str | Path, clock: Clock, symbols: list[str]):
        self.dir = Path(data_dir)
        self.clock = clock
        self._frames: dict[tuple[str, str], pd.DataFrame] = {}
        has_15m = all((self.dir / f"{s}_15m.parquet").exists() for s in symbols)
        self.fine_interval = "15m" if has_15m else "4h"

    async def close(self) -> None:
        return None

    def _frame(self, symbol: str, interval: str) -> pd.DataFrame:
        key = (symbol, interval)
        if key not in self._frames:
            path = self.dir / f"{symbol}_{interval}.parquet"
            if not path.exists():
                raise FileNotFoundError(f"replay data missing: {path}")
            self._frames[key] = pd.read_parquet(path).sort_values("ts").reset_index(drop=True)
        return self._frames[key]

    def end_of_data(self) -> datetime:
        """Close time of the last stored BTC 4h candle: the simulated clock stops there."""
        return self._frame("BTCUSDT", "4h").ts.iloc[-1].to_pydatetime() + timedelta(hours=4)

    async def klines(self, symbol: str, interval: str, start: datetime | None = None,
                     end: datetime | None = None, limit: int = 1000) -> list[Kline]:
        df = self._frame(symbol, interval)
        now = self.clock.now()
        step = timedelta(seconds=interval_seconds(interval))
        m = df.ts <= pd.Timestamp(now)
        if start is not None:
            m &= df.ts >= pd.Timestamp(start)
        if end is not None:
            m &= df.ts <= pd.Timestamp(end)
        part = df.loc[m]
        if start is not None:
            part = part.head(limit)
        else:
            part = part.tail(limit)
        out = []
        for r in part.itertuples(index=False):
            ot = r.ts.to_pydatetime()
            ct = ot + step
            if ct <= now:
                out.append(Kline(ot, ct, r.open, r.high, r.low, r.close, r.volume, r.quote_volume,
                                 int(r.trades), r.taker_buy_base, r.taker_buy_quote))
            else:  # in progress: only the open is known
                out.append(Kline(ot, ct, r.open, r.open, r.open, r.open, 0.0))
        return out

    async def klines_range(self, symbol: str, interval: str, start: datetime, end: datetime) -> list[Kline]:
        return await self.klines(symbol, interval, start, end, limit=10**7)

    async def prices(self, symbols: list[str]) -> dict[str, float]:
        out = {}
        now = self.clock.now()
        for s in symbols:
            df = self._frame(s, self.fine_interval)
            step = pd.Timedelta(seconds=interval_seconds(self.fine_interval))
            closed = df[df.ts + step <= pd.Timestamp(now)]
            if len(closed):
                out[s] = float(closed.close.iloc[-1])
        return out
