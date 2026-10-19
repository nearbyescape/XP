"""Download and consolidate historical Binance klines for the research universe.

Two sources:
  * static-klines (default): community mirror https://github.com/finom/static-klines of Binance's
    public REST API, top-10 USDT spot pairs only. This is what the published research used.
  * binance: the official Binance data portal (https://data.binance.vision), any symbol, spot or
    USDT-M futures. Use this to re-validate on a larger production universe. NOTE: the research
    sandbox could not reach data.binance.vision, so this path is written against the portal's
    documented layout but was not exercised end-to-end here; check the first build's output.

Usage:
    python research/data/fetch_klines.py            # static-klines: download + build parquet
    python research/data/fetch_klines.py --build    # only rebuild parquet from raw cache
    python research/data/fetch_klines.py --source binance --market um --intervals 4h \
        --symbols BTCUSDT,ETHUSDT,SOLUSDT,... --start 2019-01
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "raw"
PARQUET_DIR = ROOT / "parquet"
BASE_URL = "https://raw.githubusercontent.com/finom/static-klines/main/.klines-cache"

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
]

COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore",
]


def _window_starts(interval: str, end: date) -> list[date]:
    """Window anchors used by the static-klines cache (see its README)."""
    starts: list[date] = []
    if interval == "1h":  # monthly windows from 2022-01
        y, m = 2022, 1
        while date(y, m, 1) <= end:
            starts.append(date(y, m, 1))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    elif interval == "4h":  # quarterly windows from 2017-07
        y, m = 2017, 7
        while date(y, m, 1) <= end:
            starts.append(date(y, m, 1))
            m += 3
            if m > 12:
                y, m = y + 1, m - 12
    elif interval == "15m":  # ISO weeks from 2024-12-30
        d = date(2024, 12, 30)
        while d <= end:
            starts.append(d)
            d += timedelta(days=7)
    else:
        raise ValueError(f"unsupported interval {interval}")
    return starts


def _download(job: tuple[str, Path]) -> str | None:
    url, path = job
    if path.exists():
        try:
            json.loads(path.read_text())
            return None
        except json.JSONDecodeError:
            pass
    for _ in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                path.write_bytes(resp.read())
            json.loads(path.read_text())
            return None
        except Exception as exc:  # noqa: BLE001 - retry on any network/parse error
            err = str(exc)
    return f"{url}: {err}"


def download(intervals: list[str], end: date) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    jobs = []
    for sym in SYMBOLS:
        for itv in intervals:
            for start in _window_starts(itv, end):
                name = f"{sym}_{itv}_{start.isoformat()}.json"
                jobs.append((f"{BASE_URL}/{sym}/{itv}/{start.isoformat()}.json", RAW_DIR / name))
    with ThreadPoolExecutor(max_workers=16) as pool:
        failures = [f for f in pool.map(_download, jobs) if f]
    for f in failures:
        print("FAILED", f, file=sys.stderr)
    print(f"downloaded/verified {len(jobs) - len(failures)}/{len(jobs)} files")


def _daily_from_4h(df: pd.DataFrame) -> pd.DataFrame:
    agg = {"open_time": "first", "open": "first", "high": "max", "low": "min", "close": "last",
           "volume": "sum", "quote_volume": "sum", "trades": "sum", "taker_buy_base": "sum",
           "taker_buy_quote": "sum"}
    return df.set_index("ts").resample("1D").agg(agg).dropna(subset=["open"]).reset_index()


def build(intervals: list[str]) -> None:
    PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    for sym in SYMBOLS:
        for itv in intervals:
            rows = []
            for path in sorted(RAW_DIR.glob(f"{sym}_{itv}_*.json")):
                rows.extend(json.loads(path.read_text()))
            if not rows:
                continue
            df = pd.DataFrame(rows, columns=COLUMNS).drop(columns=["ignore", "close_time"])
            for col in df.columns.drop("open_time"):
                df[col] = pd.to_numeric(df[col])
            df["ts"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
            df = df.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
            df.to_parquet(PARQUET_DIR / f"{sym}_{itv}.parquet", index=False)
            print(f"{sym} {itv}: {len(df):>6} bars  {df.ts.iloc[0]} -> {df.ts.iloc[-1]}")
            if itv == "4h":  # the 1d study uses daily bars resampled from 4h
                _daily_from_4h(df).to_parquet(PARQUET_DIR / f"{sym}_1d.parquet", index=False)


# ---------------------------------------------------------------------------------------------
# Official Binance data portal
# ---------------------------------------------------------------------------------------------
PORTAL = "https://data.binance.vision/data"


def _portal_csv(url: str) -> pd.DataFrame | None:
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                blob = resp.read()
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if attempt == 4:
                raise
        except (urllib.error.URLError, ConnectionError, TimeoutError):  # dropped connections: retry
            if attempt == 4:
                raise
        time.sleep(2 ** attempt)
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        raw = zf.read(zf.namelist()[0]).decode()
    df = pd.read_csv(io.StringIO(raw), header=None)
    if not str(df.iat[0, 0]).isdigit():  # futures files carry a header row
        df = df.iloc[1:]
    df.columns = COLUMNS
    df = df.drop(columns=["ignore", "close_time"]).apply(pd.to_numeric)
    # spot files switched to microsecond timestamps in 2025
    df["open_time"] = df["open_time"].where(df["open_time"] < 10**14, df["open_time"] // 1000)
    return df


def build_from_binance(symbols: list[str], intervals: list[str], market: str, start: str) -> None:
    PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    prefix = f"{PORTAL}/futures/um" if market == "um" else f"{PORTAL}/spot"
    today = date.today()
    months = pd.period_range(start, pd.Period(today, "M") - 1, freq="M")
    for sym in symbols:
        for itv in intervals:
            urls = [f"{prefix}/monthly/klines/{sym}/{itv}/{sym}-{itv}-{m}.zip" for m in months]
            first_of_month = date(today.year, today.month, 1)
            urls += [f"{prefix}/daily/klines/{sym}/{itv}/{sym}-{itv}-{d.isoformat()}.zip"
                     for d in (first_of_month + timedelta(days=i)
                               for i in range((today - first_of_month).days))]
            with ThreadPoolExecutor(max_workers=8) as pool:
                parts = [p for p in pool.map(_portal_csv, urls) if p is not None]
            if not parts:
                print(f"{sym} {itv}: no data")
                continue
            df = pd.concat(parts, ignore_index=True)
            df["ts"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
            df = df.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
            df.to_parquet(PARQUET_DIR / f"{sym}_{itv}.parquet", index=False)
            if itv == "4h":
                _daily_from_4h(df).to_parquet(PARQUET_DIR / f"{sym}_1d.parquet", index=False)
            print(f"{sym} {itv}: {len(df):>6} bars  {df.ts.iloc[0]} -> {df.ts.iloc[-1]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true", help="skip download, rebuild parquet only")
    parser.add_argument("--intervals", default="15m,1h,4h")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--source", default="static-klines", choices=["static-klines", "binance"])
    parser.add_argument("--market", default="um", choices=["um", "spot"], help="binance source only")
    parser.add_argument("--symbols", default=",".join(SYMBOLS), help="binance source only")
    parser.add_argument("--start", default="2019-01", help="binance source only (YYYY-MM)")
    args = parser.parse_args()
    intervals = args.intervals.split(",")
    if args.source == "binance":
        build_from_binance(args.symbols.split(","), intervals, args.market, args.start)
        return
    if not args.build:
        download(intervals, date.fromisoformat(args.end))
    build(intervals)


if __name__ == "__main__":
    main()
