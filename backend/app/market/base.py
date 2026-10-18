"""Market data contract shared by the Binance client and the historical replay source."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

UNITS = {"m": 60, "h": 3600, "d": 86400}


def interval_seconds(interval: str) -> int:
    return int(interval[:-1]) * UNITS[interval[-1]]


def floor_time(t: datetime, interval: str) -> datetime:
    step = interval_seconds(interval)
    ts = int(t.timestamp()) // step * step
    return datetime.fromtimestamp(ts, tz=timezone.utc)


@dataclass
class Kline:
    open_time: datetime
    close_time: datetime          # = open_time + interval (exclusive end)
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float = 0.0
    trades: int = 0
    taker_buy_base: float = 0.0
    taker_buy_quote: float = 0.0

    def is_closed(self, now: datetime) -> bool:
        return self.close_time <= now

    def as_row(self, symbol: str, interval: str) -> dict:
        d = asdict(self)
        d.pop("close_time")
        d.update(symbol=symbol, interval=interval)
        return d


def kline_from_binance(raw: list, interval: str) -> Kline:
    ot = datetime.fromtimestamp(raw[0] / 1000, tz=timezone.utc)
    return Kline(
        open_time=ot, close_time=ot + timedelta(seconds=interval_seconds(interval)),
        open=float(raw[1]), high=float(raw[2]), low=float(raw[3]), close=float(raw[4]),
        volume=float(raw[5]), quote_volume=float(raw[7]), trades=int(raw[8]),
        taker_buy_base=float(raw[9]), taker_buy_quote=float(raw[10]),
    )


class MarketData(Protocol):
    name: str
    fine_interval: str  # resolution used to track open signals

    async def klines(self, symbol: str, interval: str, start: datetime | None = None,
                     end: datetime | None = None, limit: int = 1000) -> list[Kline]:
        """Candles with open_time in [start, end]; may include the in-progress candle."""

    async def klines_range(self, symbol: str, interval: str, start: datetime,
                           end: datetime) -> list[Kline]:
        """All candles in [start, end], paginating as needed."""

    async def prices(self, symbols: list[str]) -> dict[str, float]: ...

    async def close(self) -> None: ...
