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
| `backtest/strategies.py` | All rule-based strategy families (S1–S10), incl. the two validated ones: `regime_gated_pullback` (S9 → **RGP-4H**) and `liquidity_sweep` (S10 → **RSR-4H**) |
| `run_research.py` | Parameter grids per family; in-sample / out-of-sample metrics per parameter set → `results/grid_*.csv` |
| `analyze_candidate.py` | Deep dive on one config: per year/side/coin, exit mix, clustering, exposure, cost stress, 15m re-validation |
| `meta_label.py` | Strategy C (**MLR-4H**): features, triple-barrier labels, LightGBM with quarterly walk-forward retraining, training-calibrated thresholds; `--export` trains the production model |
| `results/models/` | Production MLR-4H model (LightGBM text format) + JSON with feature list, threshold and training cutoff |
| `results/meta_preds_*.parquet` | Walk-forward out-of-sample predictions (2022 → Oct 2026), per coin, candle and side |
| `pairs.py` | Market-neutral pair-spread reversion (45 pairs) |
| `cme_gap.py` | CME weekend-gap fill study |
| `summarize.py` | Funnel table across all grids → `results/summary_funnel.md` |
| `universe_study.py` | Universe expansion (Oct 2026): C retrained on 20 coins (`meta_label.py --universe 20`) vs today's 10, live lifecycle and session, pass criteria fixed up front → `results/universe20.md` (failed: stay on 10) |
| `tp_ladder.py` | TP1 / TP2 / TP3 study: target distances per coin, hit rates by target level, scale-out plans with and without a break-even stop → `results/tp_ladder_<tf>.md` |
| `latest_signals.py` | Reference implementation of RGP-4H / RSR-4H / MLR-4H on the latest (or any) closed candle. **Parity test for the live engine** |
| `results/candidates/*_trades.csv` | Every simulated trade of the validated strategies (A/B: 2018 → Oct 2026; C: 2022 → Oct 2026, by threshold) |
| `results/grids/*.csv.gz` | Every parameter set of every grid with in-sample and out-of-sample metrics |

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
python research/meta_label.py --tf 4h --tp 0.5 --sl 3.0 --bars 24 --oos 2022-01-01   # walk-forward
python research/meta_label.py --tf 4h --tp 0.5 --sl 3.0 --bars 24 --export           # production model
python research/latest_signals.py --at 2026-09-26T16:00Z
python research/summarize.py
```
