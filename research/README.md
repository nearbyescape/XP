# Signal strategy research harness

Backtesting and validation code behind
[`docs/crypto-signal-strategy-research.md`](../docs/crypto-signal-strategy-research.md).

## Setup

```bash
pip install pandas numpy numba pyarrow lightgbm scikit-learn tabulate
python research/data/fetch_klines.py          # ~1,900 files, ~200 MB -> research/data/parquet/
```

Market data is git-ignored. Use `--source binance --market um --symbols ...` to pull any USDT-M
perpetual from the official Binance data portal (needed for the universe-expansion study).

## Files

| Path | Purpose |
|---|---|
| `backtest/engine.py` | Numba bar-by-bar simulator: next-open entries, resting TP/SL, same-bar ⇒ stop first, gap fills at open, limit entries with trade-through requirement, TP1 + break-even, time stops, maker/taker cost model |
| `backtest/indicators.py` | EMA, SMA, Wilder RSI/ATR/ADX, Bollinger, rolling VWAP, z-score (all known at bar close) |
| `backtest/strategies.py` | All tested strategy families (S1–S10), incl. the two validated ones: `regime_gated_pullback` (S9 → **RGP-4H**) and `liquidity_sweep` (S10 → **RSR-4H**) |
| `run_research.py` | Parameter grids per family; in-sample / out-of-sample metrics per parameter set → `results/grid_*.csv` |
| `analyze_candidate.py` | Deep dive on one config: per year/side/coin, exit mix, clustering, exposure, cost stress, 15m re-validation |
| `meta_label.py` | LightGBM meta-labelling with quarterly walk-forward retraining |
| `pairs.py` | Market-neutral pair-spread reversion (45 pairs) |
| `cme_gap.py` | CME weekend-gap fill study |
| `summarize.py` | Funnel table across all grids → `results/summary_funnel.md` |
| `latest_signals.py` | Reference implementation of RGP-4H / RSR-4H on the latest closed candle. **Parity test for the live engine** |
| `results/candidates/*_trades.csv` | Every simulated trade of the two validated strategies (2018 → Oct 2026) |

## Assumptions that matter

* Signals use **closed candles only**; entries fill at the next candle's open.
* If take-profit and stop-loss are both inside one candle, the **stop is assumed first**.
* Costs ("pro"): entry 0.07% (taker + slippage), TP 0.02% (maker), stop/time 0.08%.
* In-sample / out-of-sample splits: see `SPLITS` in `run_research.py`. Parameters were selected on
  in-sample data only.

## Typical commands

```bash
python research/run_research.py --tf 4h --cost-model pro --only S9_regime_gated_pullback,S10_liquidity_sweep
python research/analyze_candidate.py --tf 4h --strategy S10_liquidity_sweep \
  --params "{'lookback': 24, 'loc': 0.5, 'min_sweep_atr': None, 'trend_n': 200, 'regime': True, 'tp_atr': 0.5, 'sl_atr': 3.0, 'max_bars': 24}"
python research/latest_signals.py --at 2026-10-15T12:00Z
python research/summarize.py
```
