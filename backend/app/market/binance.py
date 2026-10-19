"""Binance public REST market data (spot or USDT-M futures) with host failover and backoff."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

import httpx

from .base import Kline, interval_seconds, kline_from_binance

log = logging.getLogger(__name__)

KIND = {
    "spot": {"klines": "/api/v3/klines", "price": "/api/v3/ticker/price", "max": 1000},
    "futures": {"klines": "/fapi/v1/klines", "price": "/fapi/v1/ticker/price", "max": 1500},
}


class BinanceMarketData:
    fine_interval = "1m"

    def __init__(self, base_urls: list[str], kind: str = "spot", client: httpx.AsyncClient | None = None,
                 min_interval: float = 0.0):
        if kind not in KIND:
            raise ValueError(kind)
        self.kind = kind
        self.name = f"binance_{kind}"
        self.base_urls = base_urls
        self._preferred = 0
        # Seconds between requests (0: no pacing). Bulk downloads share the server's IP weight limit
        # with the live engine, and Binance bans an IP that keeps hitting it (HTTP 418).
        self.min_interval = min_interval
        self._pace = asyncio.Lock()
        self._next_at = 0.0
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
            headers={"User-Agent": "signaldesk-engine/1.0"},
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def _wait_turn(self) -> None:
        if not self.min_interval:
            return
        async with self._pace:
            loop = asyncio.get_running_loop()
            wait = self._next_at - loop.time()
            if wait > 0:
                await asyncio.sleep(wait)
            self._next_at = loop.time() + self.min_interval

    async def _get(self, path: str, params: dict) -> object:
        last_exc: Exception | None = None
        for attempt in range(6):
            base = self.base_urls[(self._preferred + attempt) % len(self.base_urls)]
            try:
                await self._wait_turn()
                r = await self.client.get(base + path, params=params)
                if r.status_code in (418, 429):
                    wait = int(r.headers.get("Retry-After", "5"))
                    log.warning("binance rate limited (%s) on %s, sleeping %ss", r.status_code, base, wait)
                    await asyncio.sleep(min(wait, 120))
                    continue
                if r.status_code in (451, 403):  # geo-restricted host: try the next one
                    raise httpx.HTTPStatusError("restricted", request=r.request, response=r)
                r.raise_for_status()
                self._preferred = (self._preferred + attempt) % len(self.base_urls)
                return r.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_exc = exc
                log.warning("binance %s%s failed (%s), attempt %d", base, path, exc, attempt + 1)
                await asyncio.sleep(min(2 ** attempt, 20))
        raise RuntimeError(f"Binance request failed after retries: {path} {params}") from last_exc

    async def klines(self, symbol: str, interval: str, start: datetime | None = None,
                     end: datetime | None = None, limit: int = 1000) -> list[Kline]:
        params: dict = {"symbol": symbol, "interval": interval, "limit": min(limit, KIND[self.kind]["max"])}
        if start is not None:
            params["startTime"] = int(start.timestamp() * 1000)
        if end is not None:
            params["endTime"] = int(end.timestamp() * 1000)
        raw = await self._get(KIND[self.kind]["klines"], params)
        return [kline_from_binance(r, interval) for r in raw]

    async def klines_range(self, symbol: str, interval: str, start: datetime, end: datetime) -> list[Kline]:
        out: list[Kline] = []
        step = interval_seconds(interval)
        cursor = start
        page = KIND[self.kind]["max"]
        while cursor <= end:
            batch = await self.klines(symbol, interval, cursor, end, page)
            if not batch:
                break
            out.extend(batch)
            if len(batch) < page:
                break
            cursor = datetime.fromtimestamp(batch[-1].open_time.timestamp() + step, tz=cursor.tzinfo)
        return out

    async def exchange_info(self) -> dict:
        """Contract list (futures: listing dates in `onboardDate`, contract and underlying types)."""
        return await self._get({"spot": "/api/v3/exchangeInfo", "futures": "/fapi/v1/exchangeInfo"}[self.kind], {})

    async def tickers_24h(self) -> list[dict]:
        return await self._get({"spot": "/api/v3/ticker/24hr", "futures": "/fapi/v1/ticker/24hr"}[self.kind], {})

    async def prices(self, symbols: list[str]) -> dict[str, float]:
        if self.kind == "spot":
            raw = await self._get(KIND["spot"]["price"], {"symbols": json.dumps(symbols, separators=(",", ":"))})
        else:
            raw = await self._get(KIND["futures"]["price"], {})
        wanted = set(symbols)
        return {r["symbol"]: float(r["price"]) for r in raw if r["symbol"] in wanted}
