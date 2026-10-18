# Crypto Signal Strategy Research: Strategies with an 80%+ Win Rate

**Goal:** find crypto trading strategies for the signal app (web + Telegram) that win at least 80% of signals, produce a useful number of signals per day when the market allows, and still make money after fees.
**Method:** about 30,000 strategy/parameter combinations backtested on real Binance candles (2017–Oct 2026, 10 liquid USDT pairs, 15m/1h/4h/1d). Every number below is net of fees and slippage. Every strategy was tuned on one period and judged on a later period it never saw.
**Code:** everything in this report can be reproduced from [`research/`](../research/README.md).

---

## 1. Executive summary

1. **An 80%+ win rate is easy to get, and a profitable 80%+ win rate is rare.** Of 4,860 indicator strategies tested on 1h candles (taker fees on every fill), 811 showed an 80%+ win rate on the training data. **Not one of them was profitable on the out-of-sample period (2025–26).** The best reached a profit factor of 0.88. A high win rate mostly comes from where you place the take-profit and stop (TP 0.5×ATR vs SL 3×ATR wins ~85% of the time even on random prices), not from predicting direction.
2. **Two strategies passed every test.** Both run on **4h candles**, and both rely on the same idea, a **market-regime gate**: buy dips only when *both the coin and BTC* are in a 4h uptrend, and sell rallies only when both are in a downtrend.

   | Strategy | Out-of-sample signals (2022 → Oct 2026) | Win rate | Profit factor | Net per signal | Years profitable |
   |---|---:|---:|---:|---:|---:|
   | **A. Regime Pullback 4H** (RSI-2 washout in trend) | 1,800 | **90.5%** | 1.30 | +0.24% | 7 of 9 (2 break-even) |
   | **B. Regime Sweep Reversal 4H** (failed breakdown / breakout) | 947 | **88.3%** | 1.47 | +0.32% | 8 of 9 |
   | **Combined book (A + B)** | 2,708 | **89.7%** | 1.35 | +0.27% | **9 of 9** |

3. **The regime gate is the edge.** Same sweep-reversal entry, gate off: 0–18% of parameter sets were profitable out-of-sample. Gate on: 82.5%. For Strategy A, 78% of all 486 both-sided parameter variants were profitable out-of-sample, so the result sits on a wide plateau and doesn't depend on one lucky setting.
4. **Signal volume:** the combined book gave **1.55 signals/day on 10 coins** (median 9/week, 43/month). Signals arrive in clusters (0 signals on 55% of days, 5+ on the busiest 10% of days, up to 16 in a day), which is the "when the market favors it" behaviour you described. On ~40 liquid perpetual futures we estimate **~4–6 signals/day**. That extrapolation must be re-validated on the bigger universe (§7).
5. **These numbers are a good result, not an extraordinary one.** The edge per trade is real but thin: average win ≈ +1.1%, average loss ≈ −7.4%, net ≈ +0.27% per signal. Sized at 0.5% account risk per signal, the combined book returned **+4.8%/yr with a 15.8% max drawdown** out-of-sample (+9.6%/yr, 29% drawdown at 1% risk). Anyone who advertises 80–90% win rates *and* large returns is either using leverage that will eventually blow up, or not counting losses.
6. **Rejected after testing:** 1h and 15m scalping, Bollinger/VWAP reversion, capitulation-candle fading, limit-order "wick catching", trend continuation with TP1 + break-even, altcoin-vs-BTC dislocation, market-neutral pair spreads, the CME weekend-gap fill, and a LightGBM meta-labelling filter on 1h. Numbers are in §5.
7. **Product implications:** publish **closed-4h-candle signals only** (00/04/08/12/16/20 UTC). Execute on **perpetual futures with a maker take-profit**: on spot with 0.1% fees the edge mostly disappears. Show users **expectancy and R, not just win rate**. Auto-pause a strategy when its rolling statistics degrade (§8).

---

## 2. Why 80% win rate is the wrong target on its own

A strategy's win rate is mostly set by where the target and stop sit:

| TP : SL distance | Win rate a coin flip achieves (no fees) | Win rate needed to break even (TP ≈ 1.2%, round-trip cost ≈ 0.1%) |
|---|---:|---:|
| 1 : 1 | 50% | ~54% |
| 1 : 2 | 67% | ~70% |
| 1 : 4 | 80% | ~83% |
| 1 : 6 (0.5 ATR : 3 ATR) | 86% | ~87% |
| 1 : 8 (0.5 ATR : 4 ATR) | 89% | ~90% |

So "80% win rate" says almost nothing on its own. **Edge = actual win rate − break-even win rate.** Our two survivors beat break-even by **+2.5pp (A)** and **+4.6pp (B)** out-of-sample. That gap is small, which is why the protocol in §3 had to be strict.

What this means for the app and for marketing:
- Telegram channels that claim 85–95% usually count "TP1 touched" as a win, delete stopped-out calls, or never record missed entries. Independent trackers have measured top providers at ~70% against 90%+ claims ([Telegram signal accuracy review](https://templo.panamabahai.net/2026/06/25/telegram-crypto-signals-how-to-check-accuracy-and-avoid-scams/); [Coinspot provider reviews](https://coinspot.io/en/cryptocurrencies/bitcoin/bitcoin-trading-signals-telegram/)).
- Published crypto backtests show the same pattern: strategies with 70%+ win rates come with severe drawdowns once the rare large losses are included ([49-strategy crypto backtest](https://dev.to/maymay5692/i-backtested-49-crypto-trading-strategies-heres-every-single-result-4gg5); [78 mean-reversion backtests](https://www.coinquant.ai/blog/building-a-mean-reversion-strategy-in-cryptocurrency-markets-evidence-from-78-backtests)).
- **Recommendation:** in the app, show *win rate, average win, average loss, net expectancy per signal and profit factor* together, from an append-only ledger. That transparency becomes a selling point that no competitor matches.

---

## 3. Research protocol

| Item | Setting |
|---|---|
| Data | Binance spot klines (OHLCV + taker-buy volume) via the [static-klines](https://github.com/finom/static-klines) mirror of Binance's public API |
| Universe | BTC, ETH, BNB, SOL, XRP, ADA, DOGE, AVAX, LINK, DOT (all USDT) |
| Timeframes | 15m (2025-01 → 2026-10), 1h (2022-01 → 2026-10), 4h (2017-08 → 2026-10), 1d (resampled from 4h) |
| In-sample / out-of-sample | **4h & 1d:** train 2018–2021, test 2022 → Oct 2026 (bear 2022, bull 2023–24, chop/bear 2025–26). **1h:** train 2022–2024, test 2025 → Oct 2026. **15m:** train 2025-01→09, test 2025-10 → 2026-10 |
| Entry | Signal decided on a **closed** candle, filled at the **next candle's open**. No look-ahead |
| Exits | Take-profit (limit), stop-loss (stop-market), time stop. **If TP and SL fall in the same candle, we assume the stop filled first.** Gaps fill at the open, not the level |
| Limit-order entries | Count only if price trades **through** the limit by 0.05%, so touch-and-go fills, the easiest winners, are excluded |
| Costs ("pro" model) | Entry 0.07% (taker fee + slippage), TP 0.02% (maker), stop/time exit 0.08% (taker + 0.03% slippage). Stress-tested up to spot-level 0.15%/side (§6) |
| Selection rule (fixed before seeing out-of-sample data) | In-sample win rate ≥ 80%, profit factor ≥ 1.2, enough trades. **Out-of-sample pass** = win rate ≥ 80% **and** profit factor ≥ 1.15 |
| Robustness | We pick the *centre of a plateau* of passing parameters, not the single best one. Per-year, per-coin and per-side breakdowns. Re-simulation on 15m candles to remove same-candle TP/SL ambiguity. Cost stress test |

Choosing the in-sample-best parameters (highest t-stat) for the regime-gated pullback would have produced a long-only variant with out-of-sample profit factor **0.98**. The surviving configuration was chosen on a structural prior instead: trade both sides symmetrically, at the centre of the plateau. We call this out because it is the most common way backtests mislead.

---

## 4. The validated strategies

### Strategy A: Regime Pullback 4H (`RGP-4H`)

**Idea:** in a market where both the coin and BTC are trending, a 2-period RSI washout is usually forced selling or a stop-run inside the trend, not the start of a reversal. Fade it for a small, fast target, *only* in the direction of the regime.

**Rules (evaluate at every 4h close, UTC 00/04/08/12/16/20):**

```
coin_trend = UP   if close > EMA200 and EMA200 > EMA200[24 bars ago]
             DOWN if close < EMA200 and EMA200 < EMA200[24 bars ago]
btc_trend  = same definition on BTCUSDT 4h      (for BTC itself, use its own trend)

LONG  if coin_trend == UP   and btc_trend == UP   and RSI(2) < 5
SHORT if coin_trend == DOWN and btc_trend == DOWN and RSI(2) > 95

entry      = market, at the open of the next 4h candle
take-profit= entry ± 0.5 × ATR(14)            (resting limit order: maker fee)
stop-loss  = entry ∓ 4.0 × ATR(14)            (stop-market)
time stop  = close at market after 48 candles (8 days)
one open signal per coin; ignore new triggers on that coin while one is open
```
RSI and ATR use Wilder smoothing. EMA = standard exponential moving average on close.

**Results** (net of costs, 10 coins):

| Period | Signals | Signals/day | Win rate | Break-even win rate | Avg win | Avg loss | Net/signal | Profit factor | Max losing streak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| In-sample 2018–21 | 996 | 0.68 | 90.2% | 87.1% | +1.71% | −11.60% | +0.40% | 1.35 | 7 |
| **Out-of-sample 2022 → Oct 2026** | **1,800** | **1.03** | **90.5%** | 88.0% | +1.15% | −8.40% | **+0.24%** | **1.30** | 7 |

Profit factor by year: 2018 1.00 · 2019 1.55 · 2020 1.57 · 2021 1.35 · 2022 1.51 · 2023 2.03 · 2024 1.16 · 2025 1.00 · 2026 1.20.
Out-of-sample by side: long PF 1.18 (813 signals), short PF 1.43 (987 signals). Every coin was profitable out-of-sample (PF 1.05 XRP → 1.83 DOGE).
Typical distances: TP ≈ 1.2%, SL ≈ 9.8% (median). 90% of signals close at TP. Median hold is 4h (one candle).

**Robust region (all validated out-of-sample):** RSI(2)<5 to RSI(3)<15 · EMA 100–800 · TP 0.5–0.75 ATR · SL 3–4 ATR · time stop 24–48 candles.

### Strategy B: Regime Sweep Reversal 4H (`RSR-4H`)

**Idea:** a "liquidity sweep". Price runs below the 4-day low (triggering the stops that sit there), then closes back above it. When the regime agrees, those stops become the fuel for the snap-back. Same regime gate as A, but a different trigger: only 60 of 1,476 signals coincide with A's.

**Rules:**

```
prior_low  = lowest low of the previous 24 candles (excluding the current one)
prior_high = highest high of the previous 24 candles
loc        = (close − low) / (high − low)          # where the candle closed in its range

LONG  if low < prior_low  and close > prior_low  and loc > 0.5
         and coin_trend == UP   and btc_trend == UP
SHORT if high > prior_high and close < prior_high and loc < 0.5
         and coin_trend == DOWN and btc_trend == DOWN

entry = next 4h open · TP = 0.5 × ATR(14) · SL = 3.0 × ATR(14) · time stop = 24 candles (4 days)
```

| Period | Signals | Signals/day | Win rate | Break-even win rate | Avg win | Avg loss | Net/signal | Profit factor | Max losing streak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| In-sample 2018–21 | 529 | 0.36 | 87.3% | 85.0% | +1.61% | −9.12% | +0.25% | 1.21 | 4 |
| **Out-of-sample 2022 → Oct 2026** | **947** | **0.54** | **88.3%** | 83.7% | +1.12% | −5.74% | **+0.32%** | **1.47** | 5 |

Profit factor by year: 2018 1.40 · 2019 1.02 · 2020 1.13 · 2021 1.31 · 2022 1.73 · 2023 2.56 · **2024 0.88** · 2025 2.05 · 2026 1.17.
Out-of-sample by side: long PF 1.50, short PF 1.45. Weakest coins: AVAX, BNB, XRP (≈ break-even).

### Combined book (A + B)

| Year | Signals | Win rate | Profit factor | Net/signal |
|---|---:|---:|---:|---:|
| 2018 | 239 | 87.0% | 1.08 | +0.10% |
| 2019 | 320 | 89.1% | 1.31 | +0.28% |
| 2020 | 401 | 90.8% | 1.37 | +0.35% |
| 2021 | 544 | 89.0% | 1.34 | +0.49% |
| 2022 | 619 | 91.3% | 1.57 | +0.46% |
| 2023 | 533 | 93.2% | 2.13 | +0.48% |
| 2024 | 546 | 86.8% | 1.05 | +0.05% |
| 2025 | 563 | 88.8% | 1.22 | +0.18% |
| 2026 (to Oct) | 447 | 88.1% | 1.17 | +0.12% |

- 34 of 36 quarters had a win rate ≥ 80%. The worst quarter was 57%. Expect a rough quarter roughly every 4–5 years.
- Signal flow out-of-sample: **1.55/day** on average; 0 on 55% of days; 5+ on the busiest 10% of days; up to 16. 9/week median, 43/month median (range 5–80).
- Exposure: on average 2.8 open positions; 95th percentile 8; maximum 17 (all 10 coins × both strategies in a cascade).
- **Account-level results (out-of-sample 2022 → Oct 2026, risk-based sizing):**

  | Risk per signal | Total return | CAGR | Max drawdown |
  |---:|---:|---:|---:|
  | 0.25% | +12.0% | +2.4% | 8.2% |
  | **0.50% (recommended default)** | **+25.2%** | **+4.8%** | **15.8%** |
  | 1.00% | +55.5% | +9.6% | 29.2% |

  Capping the number of simultaneous positions did **not** reduce drawdown: the drawdowns come from losing streaks at regime transitions (deepest trough Feb 2025), not from clustering. Risk per signal is the control that matters.

---

## 5. What failed, and why it matters for the product

| Family | Best timeframe tested | Out-of-sample result | Verdict |
|---|---|---|---|
| RSI(2)/RSI(3) pullback without market gate | 4h | Long-only and short-only variants mostly ≈ break-even; 24 of 170 qualifiers survive | Weaker version of A |
| Bollinger snap-back (2–3σ re-entry) | 1h / 4h | 0 survivors; median net −0.19% to −0.23%/trade | ✗ |
| VWAP stretch + RSI(2) | 1h / 4h | 0 survivors; in-sample 80% win rate decays to 73% out-of-sample | ✗ |
| Capitulation candle fade (body, volume, taker-sell filters) | 1h / 4h | 0 survivors; −0.26% to −0.31%/trade | ✗ |
| Altcoin vs BTC residual dislocation | 1h / 4h | 0 survivors | ✗ |
| Trend continuation with TP1 + break-even (Telegram-style) | 1h / 4h | 0 qualifiers; median −0.40% (1h) to −0.53% (4h) per trade | ✗ |
| Limit-order wick catcher (Keltner deep bids) | 1h / 4h | 0 qualifiers; median −0.33%/trade on 4h; 55–66% win rate on 1h. Adverse selection: the fills you get are the moves that keep going | ✗ |
| RSI extreme with limit entry below the close | 4h | 0 qualifiers | ✗ |
| Regime-gated A/B on **1h** | 1h | Median out-of-sample −0.08% to −0.16%/trade; 2 isolated survivors (noise) | ✗ |
| Regime-gated A/B on **15m** | 15m | _see §5.1_ | _see §5.1_ |
| Market-neutral pair spreads (45 pairs) | 4h | Win rate ≈ 50%; profit factor ≈ 1.0 at best, median −0.18%/trade | ✗ |
| CME weekend-gap fill (BTC, ETH) | 1h | 2022–24: win rate 27–66%, profit factor 0.2–0.7. Gaps often fill, but only after the stop | ✗ (myth) |
| LightGBM meta-labelling (45 features, quarterly walk-forward) | 1h | Ranks well (win rate 60% → 74% across confidence buckets) but the top bucket is only +0.02%/trade; never reaches 80% | ✗ standalone |
| LightGBM meta-labelling | 4h | _see §5.1_ | _see §5.1_ |

The full funnel per family and timeframe is in [`research/results/summary_funnel.md`](../research/results/summary_funnel.md).

**Why intraday fails:** crypto *does* mean-revert at 1–4h horizons, and more strongly after large moves ([De Nicola, *Ledger* 2021](https://ledger.pitt.edu/ojs/ledger/article/view/213); [Corbet & Katsiampa 2018](https://shura.shu.ac.uk/23470/)). A 2026 working paper finds that 15-minute reversal is concentrated after aggressive taker flow but averages ~1.3 bp gross, below a 5 bp round-trip cost ([Kitron & Wengrowicz, arXiv 2608.21888](https://arxiv.org/pdf/2608.21888); preprint, not peer-reviewed). Our 1h/15m grids confirm it: the reversal exists, but fees and noise eat it. On 4h the moves are 3–4× larger relative to costs, so the edge survives.

**Why the edge sits in volatile periods:** setups whose 4×ATR stop would be wider than 8–15% were the *profitable* ones. Filtering them out cut out-of-sample profit factor to ~1.0. Big dislocations revert hardest, so don't filter them out. Control them with **position sizing by stop distance** instead.

### 5.1 Results still to append
_(filled in below once the 15m, 1d and 4h-meta runs finish)_

---

## 6. Execution and cost sensitivity

| Execution (out-of-sample) | A profit factor | B profit factor |
|---|---:|---:|
| Pro: maker TP, taker entry/stop (baseline) | 1.30 | 1.47 |
| Everything taker (0.07%/side) | 1.25 | 1.41 |
| Taker + 0.15% stop slippage | 1.23 | 1.37 |
| **Spot exchange: 0.1% fee + 0.05% slippage per side** | **1.05** | **1.17** |

- **Futures (USDT-M perpetuals) at 1× leverage with a resting TP limit** is the intended execution. On spot exchanges with 0.1% fees, Strategy A becomes marginal.
- **Re-simulating with 15m candles** (2025-01 → 2026-10) gave identical results to 4h, because with 0.5 ATR / 3–4 ATR levels a single 4h candle almost never touches both. The conservative same-candle assumption costs nothing here.
- Funding is ignored: the median hold is ~4h and the 90th percentile is ~48h, so the cost is ±0.01–0.03% per trade, which is noise at this edge size. Add it to live P&L tracking anyway.
- **For users in India:** the 1% TDS and 30% tax on crypto (VDA) gains, plus the fee schedules on Indian spot venues, can absorb an edge of +0.27% per trade. Have this reviewed before offering paid signals to Indian retail users on spot.

---

## 7. How to get "a decent amount of signals daily"

| Lever | Expected effect | Status |
|---|---|---|
| Expand universe from 10 → ~40 liquid USDT-M perps (≥ $50M daily volume) | ~0.155 signals/coin/day → **~4–6/day** (correlated alts cluster, so less than linear) | Must re-run the harness on the bigger universe: `research/data/fetch_klines.py --source binance` (Binance data portal) |
| Run A and B together (already done above) | +50% vs A alone, only 4% overlap | ✓ |
| Use the robust-region variant RSI(3) < 15 instead of RSI(2) < 5 for A | +27% signals (2,286 vs 1,800 out-of-sample) at win rate 90.1%, PF 1.25 | ✓ validated |
| 1h / 15m versions | More signals, but they lose money | ✗ do not ship |

Signals are regime-dependent by design: only one side is active at a time, and choppy months produce few (June 2025: 5 signals; busiest month: 80). Hit rates are highest in clean trends (2022 bear 91%, 2023 bull 93%) and dip at regime transitions (2024: 87%, Q1 2025 drawdown). Explain this on the website ("Regime: BTC ↑ · longs active, shorts paused"); it protects trust during quiet or rough weeks.

---

## 8. Production blueprint for the signal engine

**Data and scheduling**
- Binance USDT-M futures WebSocket `kline_4h` (act only on `x: true`, closed candles) plus REST backfill on reconnect. Keep Bybit/OKX as a fallback feed.
- Run evaluation at each 4h close plus about 5s. Compute EMA/RSI/ATR incrementally, and recompute from REST after any gap.
- Idempotency key: `strategy:symbol:candle_open_time`. Never publish twice; never repaint.

**Signal object (web and Telegram share one schema)**
```json
{
  "id": "RSR-4H:SOLUSDT:2026-10-18T08:00Z",
  "strategy": "RSR-4H", "symbol": "SOLUSDT", "side": "LONG",
  "signal_candle_close": "2026-10-18T12:00:00Z",
  "entry_ref": 142.30, "take_profit": 144.05, "stop_loss": 131.80,
  "time_stop": "2026-10-22T12:00:00Z",
  "tp_pct": 1.23, "sl_pct": -7.38, "rr": 0.17,
  "regime": {"coin": "UP", "btc": "UP"},
  "suggested_risk_pct": 0.5, "suggested_notional_pct": 6.8,
  "status": "ACTIVE"
}
```
Lifecycle: `ACTIVE → TP_HIT | SL_HIT | TIME_EXIT` (tracked on 1m klines). Store fill timestamps, MFE/MAE, and net P&L in % and R.

**Telegram message template**
```
🟢 LONG  SOL/USDT Perp   ·  RSR-4H (Sweep Reversal)
Entry  ~142.30  (4H close 12:00 UTC)
TP     144.05  (+1.23%)   ← place as LIMIT
SL     131.80  (−7.38%)
Time   exit by 22 Oct 12:00 UTC
Size   risk 0.5% of account → ~6.8% notional, 1× leverage
Regime BTC ↑ · SOL ↑     Strategy OOS: 88% hit · +0.32%/signal
```
Edit the original message (or reply in thread) when the signal closes, so the channel history becomes the public audit trail.

**Risk and trust controls**
- Size by stop distance: `notional = account × risk% / SL%`. Cap notional per signal at 20% and total open risk at 5% of the account.
- **Kill switch (calibrated on 2018–2026):** pause a strategy (switch to paper-only) when the rolling last-150-signal win rate < 82% **or** profit factor < 0.75. Historically the 5th percentiles were 82.7% and 0.73; the switch would have been active for ~7% of signals, concentrated in 2024 and early 2025. Resume after 50 paper signals with profit factor > 1.1.
- Public, append-only ledger: every signal, including losses and time-outs, with net-of-fee results. No deletions.
- Use a closed universe (liquidity-screened monthly). Never signal a coin listed within the last 60 days: indicators need 200+ candles of 4h history.

**Before charging money**
1. Re-run the harness on the full production universe (≥ 30 perps).
2. Paper-trade A + B live for **6–8 weeks**, matching every live signal against the backtest engine on the same candles (must be 100% identical).
3. Then a small live book with real fills, to measure actual slippage versus the 0.03% assumption.

---

## 9. Next research (needs data we didn't have here)

- **Funding rate, open interest and liquidation feeds** (Binance/Bybit, Coinglass). Crowded-positioning filters are the most promising way to raise A/B's edge above break-even (e.g. skip longs when funding is in the top decile).
- **Meta-labelling on 4h signals** using those derivatives features: decide for each A/B signal whether to take it.
- **Universe expansion study** (§7), and a liquidity-tier cost model for smaller alts.
- **Delta-neutral funding carry** as a separate low-volatility "yield signal" product line. It isn't directional, so it can't be judged by win rate. It needs funding history to evaluate.

---

## 10. Reproduce

```bash
pip install pandas numpy numba pyarrow lightgbm scikit-learn tabulate
python research/data/fetch_klines.py                       # download + build parquet (≈200 MB)
python research/run_research.py --tf 4h --cost-model pro   # full grids (also --tf 1h / 15m / 1d)
python research/analyze_candidate.py --tf 4h --strategy S9_regime_gated_pullback \
  --params "{'rsi_n': 2, 'rsi_lo': 5, 'trend_n': 200, 'sides': 'both', 'tp_atr': 0.5, 'sl_atr': 4.0, 'max_bars': 48}"
python research/summarize.py                               # funnel table
```
See [`research/README.md`](../research/README.md) for the file map and engine assumptions.

*This is research, not investment advice. Past performance, including out-of-sample backtests, does not guarantee future results. Crypto derivatives can lose more than the margin posted if used with leverage; the strategies above assume 1× notional.*
