import asyncio
from datetime import datetime, timezone

import httpx
import numpy as np
import pandas as pd

from app import coinstudy
from app.config import Settings
from app.market.binance import BinanceMarketData

MS = lambda s: int(pd.Timestamp(s, tz="UTC").timestamp() * 1000)  # noqa: E731


def contract(sym, listed="2021-01-01", **kw):
    base = {"symbol": sym, "contractType": "PERPETUAL", "quoteAsset": "USDT", "status": "TRADING",
            "underlyingType": "COIN", "baseAsset": sym[:-4], "onboardDate": MS(listed)}
    base.update(kw)
    return base


INFO = {"symbols": [
    contract("BTCUSDT"), contract("ETHUSDT"),
    contract("AAAUSDT"), contract("BBBUSDT"), contract("CCCUSDT"),
    contract("USDCUSDT"),                                    # stablecoin
    contract("BTCDOMUSDT", underlyingType="INDEX"),          # index contract
    contract("NEWUSDT", listed="2024-06-01"),                # listed too recently
    contract("OLDUSDT", status="SETTLING"),                  # no longer trading
    contract("BTCUSDT_250926", contractType="CURRENT_QUARTER"),
]}
TICKERS = [{"symbol": s, "quoteVolume": str(v)} for s, v in
           [("BTCUSDT", 9e9), ("ETHUSDT", 5e9), ("AAAUSDT", 3e8), ("BBBUSDT", 9e8), ("CCCUSDT", 1e8),
            ("USDCUSDT", 2e9), ("BTCDOMUSDT", 5e9), ("NEWUSDT", 8e9), ("OLDUSDT", 7e9)]]


def test_candidates_follow_the_fixed_rules():
    picked = coinstudy.candidates(INFO, TICKERS, {"BTCUSDT", "ETHUSDT"}, "2023-01-01", top=2)
    assert [c["symbol"] for c in picked] == ["BBBUSDT", "AAAUSDT"]  # by 24h volume, exclusions applied
    assert picked[0]["volume"] == 9e8 and picked[0]["listed"].year == 2021
    assert [c["symbol"] for c in coinstudy.candidates(INFO, TICKERS, set(), "2023-01-01", 10)] == [
        "BTCUSDT", "ETHUSDT", "BBBUSDT", "AAAUSDT", "CCCUSDT"]


def fake_binance():
    """Synthetic 4H futures candles (mean-reverting random walks) behind the futures endpoints."""
    times = pd.date_range("2023-07-01", "2024-07-01", freq="4h", tz="UTC")
    rng = np.random.default_rng(7)
    series = {}
    for sym in ("BTCUSDT", "ETHUSDT", "AAAUSDT", "BBBUSDT", "CCCUSDT"):
        x, px = 0.0, []
        for _ in times:
            x = 0.97 * x + rng.normal(0, 0.02)
            px.append(100 * np.exp(x + 0.0002 * len(px)))
        series[sym] = np.array(px)

    def handler(request: httpx.Request) -> httpx.Response:
        path, q = request.url.path, request.url.params
        if path.endswith("/exchangeInfo"):
            return httpx.Response(200, json=INFO)
        if path.endswith("/ticker/24hr"):
            return httpx.Response(200, json=TICKERS)
        if path.endswith("/klines"):
            px = series[q["symbol"]]
            lo, hi = int(q.get("startTime", 0)), int(q.get("endTime", 10**15))
            rows = []
            for i, t in enumerate(times):
                ms = int(t.timestamp() * 1000)
                if lo <= ms <= hi:
                    o, c = (px[i - 1] if i else px[0]), px[i]
                    rows.append([ms, str(o), str(max(o, c) * 1.004), str(min(o, c) * 0.996), str(c), "10",
                                 ms + 14_399_999, "1000", 5, "4", "400", "0"])
            return httpx.Response(200, json=rows[:int(q.get("limit", 500))])
        return httpx.Response(404)
    return BinanceMarketData(["https://fapi.test"], "futures", client=httpx.AsyncClient(
        transport=httpx.MockTransport(handler)))


async def test_study_runs_end_to_end_without_writing_anything():
    lines = []
    settings = Settings(universe="BTCUSDT,ETHUSDT", environment="test")
    out = await coinstudy.run(settings, top=2, start="2024-01-01", split="2024-04-01",
                              now=datetime(2024, 7, 1, tzinfo=timezone.utc), market=fake_binance(),
                              say=lines.append)
    text = "\n".join(lines)
    assert [c["symbol"] for c in out["candidates"]] == ["BBBUSDT", "AAAUSDT"]
    assert "Candidates: top 2 by 24h volume" in text and "VERDICT:" in text
    assert set(out["baskets"]) == {"Current 2 coins (A+B)", "All 2 candidates (A+B)",
                                   f"Passing {len(out['passing'])} coins (A+B)"}
    for c in out["candidates"]:
        assert c["pass"] == (c["selection"]["n"] >= 15 and c["selection"]["wr"] >= 0.85
                             and (c["selection"]["pf"] is None or c["selection"]["pf"] >= 1.0))
    if out["recommend"]:
        assert "UNIVERSE=BTCUSDT,ETHUSDT," in text


async def test_bulk_downloads_are_paced():
    """The study shares the server's Binance weight limit with the live engine: requests go out spaced."""
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(asyncio.get_running_loop().time())
        return httpx.Response(200, json={"symbols": []})

    market = BinanceMarketData(["https://fapi.test"], "futures", min_interval=0.05,
                               client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await asyncio.gather(*(market.exchange_info() for _ in range(4)))
    gaps = np.diff(sorted(sent))
    assert len(sent) == 4 and gaps.min() >= 0.045
    assert 60 / coinstudy.PACE * 10 < 2400 / 2  # klines pages of weight 10: under half the IP limit
