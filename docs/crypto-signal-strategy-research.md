# Crypto Signal Strategy Research: Strategies with an 80%+ Win Rate

**Goal:** find crypto trading strategies for the signal app (web + Telegram) that win at least 80% of signals, produce a useful number of signals per day when the market allows, and still make money after fees.
**Method:** ~33,000 rule-based strategy/parameter sets plus 3 walk-forward machine-learning studies, backtested on real Binance candles (2017 → Oct 2026, 10 liquid USDT pairs, 15m/1h/4h/1d). Every number below is net of fees and slippage. Every strategy was tuned on one period and judged on a later period it never saw.
**Code:** everything in this report can be reproduced from [`research/`](../research/README.md).

---

## 1. Executive summary

1. **An 80%+ win rate is easy to get, and a profitable 80%+ win rate is rare.** Of 4,860 indicator strategies tested on 1h candles (taker fees on every fill), 811 showed an 80%+ win rate on the training data. **Not one of them was profitable out-of-sample (2025–26).** The best reached a profit factor of 0.88. A high win rate mostly comes from where you place the take-profit and stop (TP 0.5×ATR vs SL 3×ATR wins ~85% of the time even on random prices), not from predicting direction.
2. **Three strategies passed every test, all on 4h candles:**

   | Strategy | Type | Out-of-sample signals (2022 → Oct 2026, 10 coins) | Win rate | Profit factor | Net per signal | Profitable years |
   |---|---|---:|---:|---:|---:|---:|
   | **A. Regime Pullback 4H** (`RGP-4H`) | Rules | 1,800 | **90.5%** | 1.30 | +0.24% | 7 of 9 (2 break-even) |
   | **B. Regime Sweep Reversal 4H** (`RSR-4H`) | Rules | 947 | **88.3%** | 1.47 | +0.32% | 8 of 9 |
   | **C. ML-Ranked 4H** (`MLR-4H`, LightGBM) | Model, retrained quarterly | 3,240 | **88.7%** | 1.52 | +0.41% | 5 of 5 |
   | **Full book A + B + C** | | **5,829** | **89.1%** | **1.42** | **+0.33%** | 5 of 5 |

   A and B are tested over 9 years (2018–2026). C is tested walk-forward over 2022–2026, because its first model needed 2017–21 for training.
3. **Why they work:**
   - **A and B:** a *market-regime gate*. Buy dips only when **both the coin and BTC** are in a 4h uptrend; sell rallies only when both are in a downtrend. Same sweep-reversal entry, gate off: 0–18% of parameter sets were profitable out-of-sample; gate on: 82.5%.
   - **C:** a gradient-boosted model, retrained every quarter, that scores every coin and candle for the chance of hitting TP before SL. Only its top 5% most confident calls are published. Just 4% of its signals overlap with A/B, so it adds volume rather than duplicating it.
4. **Signal volume:** the full book averaged **3.3 signals/day on 10 coins** (median 20/week). Days with zero signals: 32%; busy days: 9+ (top 10%), up to 29. That is the "when the market favors it" behaviour you described. On ~40 liquid perpetual futures we estimate **~8–12 signals/day**; that must be re-validated on the bigger universe (§7).
5. **Returns are good, not miraculous.** Average win ≈ +1.2%, average loss ≈ −7.1%, net ≈ +0.33% per signal. Each signal is published with three targets (TP1/TP2/TP3 at 0.5/1.0/1.5 × ATR, stop to entry after TP1), which keeps these numbers and lets 45% of signals run to TP2 (§4, Multiple targets). Following every signal at **0.5% account risk per signal**, the full book returned **+16.2%/yr with a 13.8% max drawdown** out-of-sample (0.25% risk: +7.9%/yr, 7.1% drawdown). Anyone who advertises 80–90% win rates *and* large returns is either using leverage that will eventually blow up, or not counting losses.
6. **Rejected after testing:** anything on 1h or 15m (15m produced 5–26 signals/day, all losing), Bollinger/VWAP reversion, capitulation-candle fading, limit-order "wick catching", trend continuation with TP1 + break-even, altcoin-vs-BTC dislocation, market-neutral pair spreads, the CME weekend-gap fill, and ML on 1h. Numbers are in §5.
7. **Launch plan:**
   - **Phase 1:** go live with **A + B** (pure rules; a parity-tested reference implementation is included), and run **C in shadow mode** for 6–8 weeks.
   - **Phase 2:** promote C once its live shadow signals match the backtest.
   - **Execution:** publish **closed-4h-candle signals only**. Execute on **perpetual futures at 1× with a maker take-profit**. Show users **expectancy and R, not just win rate**. Auto-pause a strategy when its rolling statistics degrade (§8).

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

So "80% win rate" says almost nothing on its own. **Edge = actual win rate − break-even win rate.** Out-of-sample, A beats break-even by **+2.5pp**, B by **+4.6pp** and C by **+4.9pp**. These gaps are small, which is why the protocol in §3 had to be strict.

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
| In-sample / out-of-sample | **4h & 1d:** train 2018–2021, test 2022 → Oct 2026 (bear 2022, bull 2023–24, chop/bear 2025–26). **1h:** train 2022–2024, test 2025 → Oct 2026. **15m:** train 2025-01→09, test 2025-10 → 2026-10. **ML:** expanding-window walk-forward, retrained every quarter, purged at each boundary |
| Entry | Signal decided on a **closed** candle, filled at the **next candle's open**. No look-ahead |
| Exits | Take-profit (limit), stop-loss (stop-market), time stop. **If TP and SL fall in the same candle, we assume the stop filled first.** Gaps fill at the open, not the level |
| Limit-order entries | Count only if price trades **through** the limit by 0.05%, so touch-and-go fills, the easiest winners, are excluded |
| Costs ("pro" model) | Entry 0.07% (taker fee + slippage), TP 0.02% (maker), stop/time exit 0.08% (taker + 0.03% slippage). Stress-tested up to spot-level 0.15%/side (§6) |
| Selection rule (fixed before seeing out-of-sample data) | In-sample win rate ≥ 80%, profit factor ≥ 1.2, enough trades. **Out-of-sample pass** = win rate ≥ 80% **and** profit factor ≥ 1.15. ML confidence threshold = 95th percentile of the model's *training-period* scores (never tuned on the test period) |
| Robustness | We pick the *centre of a plateau* of passing parameters, not the single best one. Per-year, per-quarter, per-coin and per-side breakdowns. Re-simulation on 15m candles to remove same-candle TP/SL ambiguity. Cost stress test. A second exit geometry for the ML model |

Choosing the in-sample-best parameters (highest t-stat) for the regime-gated pullback would have produced a long-only variant (RSI(2)<15, SL 4 ATR) with out-of-sample profit factor **0.98**: the strong 2019–21 bull market flattered long-only dip-buying. The surviving configuration was chosen on a structural prior instead: trade both sides symmetrically, at the centre of the plateau. We call this out because it is the most common way backtests mislead.

---

## 4. The validated strategies

All three share one execution template: **signal on a 4h close → market entry at the next open → resting take-profit at 0.5 × ATR(14) → stop at 3–4 × ATR(14) → time stop**. RSI and ATR use Wilder smoothing; EMA is a standard exponential moving average on close. The definition shared by A and B:

```
trend(X) = UP   if close > EMA200 and EMA200 > EMA200[24 bars ago]       (on X's own 4h candles)
           DOWN if close < EMA200 and EMA200 < EMA200[24 bars ago]
coin_trend = trend(coin) ;  btc_trend = trend(BTCUSDT)   (for BTC itself, use its own trend)
```

### Strategy A: Regime Pullback 4H (`RGP-4H`)

**Idea:** in a market where both the coin and BTC are trending, a 2-period RSI washout is usually forced selling or a stop-run inside the trend, not the start of a reversal. Fade it for a small, fast target, *only* in the direction of the regime.

```
LONG  if coin_trend == UP   and btc_trend == UP   and RSI(2) < 5
SHORT if coin_trend == DOWN and btc_trend == DOWN and RSI(2) > 95
TP = entry ± 0.5 × ATR(14) · SL = entry ∓ 4.0 × ATR(14) · time stop = 48 candles (8 days)
one open signal per coin; ignore new triggers on that coin while one is open
```

| Period | Signals | Signals/day | Win rate | Break-even win rate | Avg win | Avg loss | Net/signal | Profit factor | Max losing streak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| In-sample 2018–21 | 996 | 0.68 | 90.2% | 87.1% | +1.71% | −11.60% | +0.40% | 1.35 | 7 |
| **Out-of-sample 2022 → Oct 2026** | **1,800** | **1.03** | **90.5%** | 88.0% | +1.15% | −8.40% | **+0.24%** | **1.30** | 7 |

- **Profit factor by year:** 2018 1.00 · 2019 1.55 · 2020 1.57 · 2021 1.35 · 2022 1.51 · 2023 2.03 · 2024 1.16 · 2025 1.00 · 2026 1.20.
- **Out-of-sample by side:** long PF 1.18 (813 signals), short PF 1.43 (987).
- **By coin:** every coin was profitable out-of-sample (PF 1.05 XRP → 1.83 DOGE).
- **Typical trade:** TP ≈ 1.2%, SL ≈ 9.8% (median). 90% of signals close at TP; median hold is 4h (one candle).
- **Robust region (all validated out-of-sample):** RSI(2)<5 to RSI(3)<15 · EMA 100–800 · TP 0.5–0.75 ATR · SL 3–4 ATR · time stop 24–48 candles. 78% of all 486 both-sided variants were profitable out-of-sample.

### Strategy B: Regime Sweep Reversal 4H (`RSR-4H`)

**Idea:** a "liquidity sweep". Price runs below the 4-day low (triggering the stops that sit there), then closes back above it. When the regime agrees, those stops become the fuel for the snap-back. Only 60 of B's 1,476 signals coincide with A's.

```
prior_low  = lowest low of the previous 24 candles (excluding the current one)
prior_high = highest high of the previous 24 candles
loc        = (close − low) / (high − low)                 # where the candle closed in its range
LONG  if low  < prior_low  and close > prior_low  and loc > 0.5 and coin_trend == UP   and btc_trend == UP
SHORT if high > prior_high and close < prior_high and loc < 0.5 and coin_trend == DOWN and btc_trend == DOWN
TP = 0.5 × ATR(14) · SL = 3.0 × ATR(14) · time stop = 24 candles (4 days)
```

| Period | Signals | Signals/day | Win rate | Break-even win rate | Avg win | Avg loss | Net/signal | Profit factor | Max losing streak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| In-sample 2018–21 | 529 | 0.36 | 87.3% | 85.0% | +1.61% | −9.12% | +0.25% | 1.21 | 4 |
| **Out-of-sample 2022 → Oct 2026** | **947** | **0.54** | **88.3%** | 83.7% | +1.12% | −5.74% | **+0.32%** | **1.47** | 5 |

- **Profit factor by year:** 2018 1.40 · 2019 1.02 · 2020 1.13 · 2021 1.31 · 2022 1.73 · 2023 2.56 · **2024 0.88** · 2025 2.05 · 2026 1.17.
- **Out-of-sample by side:** long PF 1.50, short PF 1.45.
- **Weakest coins:** AVAX, BNB and XRP were ≈ break-even.

### Strategy C: ML-Ranked 4H (`MLR-4H`)

**Idea:** instead of one hand-written trigger, a LightGBM classifier scores **every coin, every 4h close, both directions** for one question: *will a 0.5 ATR take-profit be hit before a 3 ATR stop within 24 candles, net of costs?* It sees 48 features:
- momentum and RSI(2/3/14)
- distance and slope of EMA 20/50/200/800
- Bollinger z-score and ATR regime
- volume surge and taker-buy ratio
- candle anatomy
- distance from the 24-bar high and low
- BTC's return, RSI and trend
- the coin's cross-sectional rank and market breadth
- hour and weekday

Only calls above a confidence threshold are published.

```
every quarter: retrain on ALL history up to the quarter start (expanding window, 100h purge gap)
threshold      = 95th percentile of the model's scores on its own last 12 training months   (≈ 0.89)
                 live since 23 Oct 2026: lowered 0.375 of the way toward the 90th           (0.881, §7)
signal         = P(win) ≥ threshold, at most 5 per 4h candle (highest P first)
TP = 0.5 × ATR(14) · SL = 3.0 × ATR(14) · time stop = 24 candles · one open signal per coin
```
The exact feature code and training recipe are in `research/meta_label.py`. A production model trained through 12 Oct 2026 is in `research/results/models/`.

| Out-of-sample (walk-forward, 19 quarterly models) | Signals | Signals/day | Win rate | Break-even win rate | Avg win | Avg loss | Net/signal | Profit factor | Max losing streak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **2022 → Oct 2026, ≤ 5 per candle** | **3,240** | **1.85** | **88.7%** | 83.8% | +1.34% | −6.89% | **+0.41%** | **1.52** | 8 |
| same, uncapped | 3,492 | 2.00 | 88.9% | 83.6% | +1.35% | −6.88% | +0.43% | 1.56 | 9 |

- **By year (uncapped):** 2022 PF 1.83 / win rate 90.9% · 2023 1.23 / 86.8% · 2024 1.67 / 89.5% · 2025 1.54 / 88.7% · 2026 1.32 / 87.3%.
- **By quarter:** **19 of 19 quarters had a win rate ≥ 80%** (worst 82.4%).
- **By side and coin:** long PF 1.89, short PF 1.25. All 10 coins were profitable (PF 1.17 BTC → 2.19 XRP).
- **Robustness:**
  - A stricter threshold (top 2.5%) gives 1,741 signals at 90.4% / PF 1.95.
  - A looser one (top 10%) gives 6,357 signals at 87.0% / PF 1.31.
  - A second exit geometry (TP 0.5 / SL 4 ATR / 48 candles) gives 2,872 signals at **92.3% / PF 1.82**.
- **What the model does *not* do:** on 1h candles the same pipeline ranks trades but never reaches an 80% win rate with positive expectancy (§5). The edge lives on 4h.
- **Risks specific to C:** model risk (retraining can drift), the feature pipeline must match the research code exactly, and the worst single loss was −32% (a 3 ATR stop during extreme volatility). Hence shadow mode first (§8).

### Combined books

| Year | A + B: signals | A + B: win rate | A + B: PF | **A + B + C: signals** | **A + B + C: win rate** | **A + B + C: PF** |
|---|---:|---:|---:|---:|---:|---:|
| 2018 | 239 | 87.0% | 1.08 | | | |
| 2019 | 320 | 89.1% | 1.31 | | | |
| 2020 | 401 | 90.8% | 1.37 | | | |
| 2021 | 544 | 89.0% | 1.34 | | | |
| 2022 | 619 | 91.3% | 1.57 | 1,227 | 90.9% | 1.64 |
| 2023 | 533 | 93.2% | 2.13 | 919 | 90.5% | 1.58 |
| 2024 | 546 | 86.8% | 1.05 | 1,341 | 88.2% | 1.33 |
| 2025 | 563 | 88.8% | 1.22 | 1,383 | 88.8% | 1.39 |
| 2026 (to Oct) | 447 | 88.1% | 1.17 | 959 | 87.1% | 1.16 |

**Account-level results** (out-of-sample 2022 → Oct 2026, following every signal, position sized so the stop costs a fixed % of the account):

| Risk per signal | A + B: CAGR | A + B: max drawdown | **A + B + C: CAGR** | **A + B + C: max drawdown** |
|---:|---:|---:|---:|---:|
| 0.25% | +2.4% | 8.2% | +7.9% | 7.1% |
| **0.50% (recommended default)** | +4.8% | 15.8% | **+16.2%** | **13.8%** |
| 1.00% | +9.6% | 29.2% | | |

- **Signal flow (A + B + C):** **3.3/day** on average; median 2 per day; 0 on 32% of days; 9+ on the busiest 10%; maximum 29. Median 20 per week.
- **Exposure (A + B):** on average 2.8 open positions, 95th percentile 8, maximum 17 (every coin signalling at once in a cascade).
- **Position caps don't help:** capping the number of simultaneous positions did **not** reduce drawdown. Drawdowns come from losing streaks at regime transitions (deepest A + B trough Feb 2025), not from clustering. **Risk per signal is the control that matters.**

### Multiple targets (TP1 / TP2 / TP3)

Every signal above was validated with one target. Subscribers expect a ladder, so we replayed every
out-of-sample signal on **1h candles** (2022 → Oct 2026, 5,977 signals; 15m candles for 2025–26 as a
cross-check) and measured what further targets would have done. Script: `research/tp_ladder.py`;
full tables: `research/results/tp_ladder_1h.md` and `tp_ladder_15m.md`.

**Distance from entry.** The target is 0.5 × ATR(14) of the 4H chart, so it scales with each coin's volatility:

| | BTC | ETH | BNB | XRP | LINK | DOT | ADA | SOL | DOGE | AVAX | All |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TP1 (median) | 0.73% | 1.02% | 0.87% | 1.13% | 1.29% | 1.26% | 1.28% | 1.35% | 1.35% | 1.43% | **1.16%** |
| Stop (median) | 4.8% | 6.7% | 5.8% | 7.5% | 8.5% | 8.1% | 8.2% | 9.0% | 8.7% | 9.1% | **7.6%** |

The median signal reaches TP1 within **5–6 hours**. TP2 and TP3 sit at 2× and 3× the TP1 distance.

**How often a target is reached before the stop** (book, within the time limit): 0.5 ATR 89.2% · 0.75 ATR 83.6% · 1.0 ATR 77.7% · 1.25 ATR 71.0% · 1.5 ATR 64.9% · 2.0 ATR 53.6%.

**Scale-out plans** (A + B + C book, one signal per coin per candle, net of costs; CAGR and drawdown at 0.5% risk per signal):

| Plan | Win rate | TP2 | TP3 | Net/signal | PF | CAGR | Max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| Single target 0.5 ATR (as validated) | 89.3% | — | — | +0.346% | 1.45 | +17.6% | 13.8% |
| **TP 0.5 / 1.0 / 1.5 ATR, close 50 / 30 / 20%, stop to entry after TP1** | **89.3%** | **45.1%** | **30.4%** | **+0.349%** | **1.46** | **+17.3%** | **14.2%** |
| Same targets, stop left at its original level | 73.8% | 77.9% | 65.2% | +0.474% | 1.45 | +24.8% | 24.9% |
| Same targets, trailing (entry after TP1, TP1 after TP2) | 89.3% | 45.1% | 23.1% | +0.345% | 1.45 | +17.0% | 14.3% |

- **Adopted: TP1 / TP2 / TP3 at 0.5 / 1.0 / 1.5 ATR, closing 50 / 30 / 20%, stop to entry after TP1.** It keeps the validated win rate (a signal that reaches TP1 ends at or above break-even, so the win rate *is* the TP1 hit rate) and the same return per signal, and 45% of signals also reach TP2. The 2025–26 cross-check on 15m candles agrees (88.5% win rate, +0.249% vs +0.253% per signal, identical drawdown).
- **Not adopted: leaving the stop where it was.** It earns about a third more per signal, but the honest win rate falls to 74% and the 2022–26 drawdown nearly doubles. Counting "TP1 touched" as a win would hide that, which is the practice §2 warns about.
- **Per strategy:** B (+0.333% vs +0.316%) and C (+0.450% vs +0.429%) gain slightly; A gives up a little (+0.204% vs +0.249%) because its 8-day holding window lets more runners drift back to entry. These differences are within the noise of a 4-year sample.
- **Selection is unchanged.** A coin is free for a new signal of the same strategy once TP1 fills, which is exactly when the validated single-target trade ended. The parity tests check that the published signals and their TP1-or-stop outcomes are identical with and without the ladder.
- **Convention:** a moved stop takes effect from the next candle, except that a candle which fills TP1 and closes back through the entry must have crossed the break-even stop after the fill; the rest then exits at entry. The live engine tracks on 1-minute candles, where this barely matters.

---

## 5. What failed, and why it matters for the product

| Family | Timeframes | Out-of-sample result | Verdict |
|---|---|---|---|
| RSI(2)/RSI(3) pullback without market gate | 4h | Long-only and short-only variants mostly ≈ break-even; 24 of 170 qualifiers survive | Weaker version of A |
| Bollinger snap-back (2–3σ re-entry) | 1h / 4h | 0 survivors; median net −0.19% to −0.23%/trade | ✗ |
| VWAP stretch + RSI(2) | 1h / 4h | 0 survivors; in-sample 80% win rate decays to 73% out-of-sample | ✗ |
| Capitulation candle fade (body, volume, taker-sell filters) | 1h / 4h | 0 survivors; −0.26% to −0.31%/trade | ✗ |
| Altcoin vs BTC residual dislocation | 1h / 4h | 0 survivors | ✗ |
| Trend continuation with TP1 + break-even (Telegram-style) | 1h / 4h | 0 qualifiers; median −0.40% (1h) to −0.53% (4h) per trade | ✗ |
| Limit-order wick catcher (Keltner deep bids) | 1h / 4h | 0 qualifiers; median −0.33%/trade on 4h; 55–66% win rate on 1h. Adverse selection: the fills you get are the moves that keep going | ✗ |
| RSI extreme with limit entry below the close | 1h / 4h | 0 qualifiers | ✗ |
| Regime-gated A/B on **1h** | 1h | Median −0.10% to −0.14%/trade; 2 isolated survivors out of 4,158 (noise). Maker take-profits don't rescue 1h either: 0 of 2,604 more pullback/VWAP/limit sets survive | ✗ |
| Regime-gated A/B on **15m** | 15m | 5–26 signals/day, but **0 of 3,186 parameter sets profitable** (median profit factor 0.63–0.77) | ✗ |
| Regime-gated A/B on **1d** | 1d | Same direction as 4h: 40 of 207 in-sample qualifiers survive, and 56% are profitable out-of-sample. But only ~0.14 signals/day on 10 coins, and samples are small (median 147 in-sample trades) | Consistent, too slow to matter; optional add-on |
| Market-neutral pair spreads (45 pairs) | 4h | Win rate ≈ 50%; profit factor ≈ 1.0 at best, median −0.18%/trade | ✗ |
| CME weekend-gap fill (BTC, ETH) | 1h | 2022–24: win rate 27–66%, profit factor 0.2–0.7. Gaps often fill, but only after the stop | ✗ (myth) |
| LightGBM meta-labelling on **1h** | 1h | Ranks trades (win rate 60% → 74% across confidence buckets) but the top bucket is only +0.02%/trade; never reaches 80% | ✗ |

The full funnel per family and timeframe is in [`research/results/summary_funnel.md`](../research/results/summary_funnel.md).

**Why intraday fails:** crypto *does* mean-revert at 1–4h horizons, and more strongly after large moves ([De Nicola, *Ledger* 2021](https://ledger.pitt.edu/ojs/ledger/article/view/213); [Corbet & Katsiampa 2018](https://shura.shu.ac.uk/23470/)). A 2026 working paper finds that 15-minute reversal is concentrated after aggressive taker flow but averages ~1.3 bp gross, below a 5 bp round-trip cost ([Kitron & Wengrowicz, arXiv 2608.21888](https://arxiv.org/pdf/2608.21888); preprint, not peer-reviewed). Our 1h/15m grids confirm it: the reversal exists, but fees and noise eat it. On 4h a typical move (ATR) is about 2× the 1h move and 4× the 15m move, while costs per trade stay the same, so the edge survives costs.

**Why the edge sits in volatile periods:** setups whose 4×ATR stop would be wider than 8–15% were the *profitable* ones. Filtering them out cut out-of-sample profit factor to ~1.0. Big dislocations revert hardest, so don't filter them out. Control them with **position sizing by stop distance** instead.

---

## 6. Execution and cost sensitivity

| Execution (out-of-sample profit factor) | A | B | C |
|---|---:|---:|---:|
| Pro: maker TP, taker entry/stop (baseline) | 1.30 | 1.47 | 1.56 |
| Everything taker (0.07%/side) | 1.25 | 1.41 | 1.51 |
| Taker + 0.15% stop slippage | 1.23 | 1.37 | 1.48 |
| **Spot exchange: 0.1% fee + 0.05% slippage per side** | **1.05** | **1.17** | **1.29** |

- **Execution venue:** USDT-M perpetual futures at 1× leverage, with a resting TP limit, is the intended execution. On spot exchanges with 0.1% fees, A becomes marginal; B and C survive.
- **15m re-simulation:** re-running A/B on 15m candles (2025-01 → 2026-10) gave results identical to 4h. With 0.5 ATR / 3–4 ATR levels, a single 4h candle almost never touches both, so the conservative same-candle assumption costs nothing here.
- **Funding:** ignored. The median hold is ~4h and the 90th percentile ~48h, so the cost is ±0.01–0.03% per trade, which is noise at this edge size. Track it in live P&L anyway.
- **For users in India:** the 1% TDS and 30% tax on crypto (VDA) gains, plus the fee schedules on Indian spot venues, can absorb an edge of +0.3% per trade. Have this reviewed before offering paid signals to Indian retail users on spot.

---

## 7. How to get "a decent amount of signals daily"

| Lever | Expected effect | Status |
|---|---|---|
| Run A + B + C together | 3.3/day on 10 coins (A alone: 1.0/day) | ✓ validated |
| Expand universe from 10 → ~40 liquid USDT-M perps (≥ $50M daily volume) | ~0.33 signals/coin/day → **~8–12/day**. Correlated alts cluster and C is capped at 5 per candle, so growth is less than linear | Re-run the harness on the bigger universe: `research/data/fetch_klines.py --source binance` |
| Looser C threshold (top 10% instead of top 5%) | C: 3.6/day instead of 2.0 at 87.0% win rate, PF 1.31 | ✓ validated (lower quality) |
| C threshold lowered part of the way from the 95th to the 90th percentile (live lifecycle and session, 10 coins, 2022-01 → 2026-10, published) | The original bar (95th) 2.12/day, PF 1.48, growth at 0.5% risk +66%, max fall 8.5%, days without a signal 44%. A quarter of the way (live 22 Oct): 2.33/day, PF 1.42, +65%, 10.2%. **0.375 of the way: 2.44/day, PF 1.43, +71%, 10.7%, 40%, every year profitable.** Halfway: 2.55/day, PF 1.39, +59%, max fall 13.3% and twice the time 6%+ below the peak | ✓ **0.375 live since 23 Oct 2026** (`THRESHOLD_STEP` in meta_label.py); halfway or lower ✗ |
| Use RSI(3) < 15 instead of RSI(2) < 5 for A | +27% A signals (2,286 vs 1,800) at 90.1% win rate, PF 1.25 | ✓ validated |
| 1h / 15m versions | More signals, but they lose money | ✗ do not ship |

Signals are regime-dependent by design. A and B only trade one side at a time, and choppy months produce few signals (June 2025: 5 A + B signals; busiest month: 80). Hit rates are highest in clean trends (2022 bear 91%, 2023 bull 93% for A + B) and dip at regime transitions (2024: 87%, Q1 2025 drawdown). Explain this on the website ("Regime: BTC ↑ · longs active, shorts paused"); it protects trust during quiet or rough weeks.

---

## 8. Production blueprint for the signal engine

**Data and scheduling**
- Binance USDT-M futures WebSocket `kline_4h` (act only on `x: true`, closed candles) plus REST backfill on reconnect. Keep Bybit/OKX as a fallback feed.
- Run evaluation at each 4h close (00/04/08/12/16/20 UTC) plus about 5s. Compute indicators incrementally, and recompute from REST after any gap.
- Idempotency key: `strategy:symbol:candle_open_time`. Never publish twice; never repaint.
- **Parity test:** `research/latest_signals.py --at <candle>` is the reference implementation of all three strategies. The live engine must produce identical signals on identical candles before launch.

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
MLR-4H signals also carry `model_prob` and the model version. Lifecycle: `ACTIVE → TP_HIT | SL_HIT | TIME_EXIT` (tracked on 1m klines). Store fill timestamps, MFE/MAE, and net P&L in % and R.

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
Edit the original message (or reply in thread) when the signal closes, so the channel history becomes the public audit trail. Telegram rate limits (≈20 messages/min per group) are not a constraint at these volumes, but batch the busy candles: one message per candle with all its signals.

**Model operations for C**
- **Retraining:** retrain quarterly on all history with `meta_label.py --export`. Version every model (training cutoff, threshold, feature list, hash), and never change features without re-running the walk-forward.
- **Promotion gate:** a new model must reproduce the walk-forward statistics on the latest quarter before it goes live. Monitor the share of signals above the threshold; if it doubles or halves versus the training period, investigate before publishing.
- **Shadow mode:** for 6–8 weeks, compute C signals live, log them, and don't publish. Compare live outcomes with the backtest on the same candles.

**Risk and trust controls**
- **Sizing:** size by stop distance: `notional = account × risk% / SL%`. Cap notional per signal at 20% and total open risk at 5% of the account.
- **Kill switch (calibrated on A + B, 2018–2026):** pause a strategy (switch to paper-only) when the rolling last-150-signal win rate < 82% **or** profit factor < 0.75. Historically the 5th percentiles were 82.7% and 0.73. The switch would have been active for ~7% of signals, concentrated in 2024 and early 2025. Resume after 50 paper signals with profit factor > 1.1.
- **Public ledger:** append-only, with every signal including losses and time-outs, and net-of-fee results. No deletions.
- **Universe:** a closed universe, liquidity-screened monthly. Never signal a coin listed within the last 60 days: indicators need 200+ candles of 4h history, and the EMA800 feature needs more.

**Before charging money**
1. Re-run the harness on the full production universe (≥ 30 perps).
2. Paper-trade A + B (and shadow C) live for **6–8 weeks**, matching every live signal against the reference implementation on the same candles (must be 100% identical for A/B).
3. Then a small live book with real fills, to measure actual slippage versus the 0.03% assumption.

---

## 9. Next research

- **Derivatives data:** add funding rate, open interest and liquidation feeds (Binance/Bybit, Coinglass) to C's feature set. Crowded-positioning information is the most promising way to widen the edge, e.g. skipping longs when funding is in the top decile.
- **Universe expansion study** (§7), and a liquidity-tier cost model for smaller alts.
- **Daily add-on:** the regime gate also works on 1d (§5), at ~0.14 signals/day on 10 coins.
- **Delta-neutral funding carry** as a separate low-volatility "yield signal" product line. It isn't directional, so it can't be judged by win rate. It needs funding history to evaluate.

---

## 10. Reproduce

```bash
pip install pandas numpy numba pyarrow lightgbm scikit-learn tabulate
python research/data/fetch_klines.py                       # download + build parquet (≈200 MB)
python research/run_research.py --tf 4h --cost-model pro   # full grids (also --tf 1h / 15m / 1d)
python research/analyze_candidate.py --tf 4h --strategy S9_regime_gated_pullback \
  --params "{'rsi_n': 2, 'rsi_lo': 5, 'trend_n': 200, 'sides': 'both', 'tp_atr': 0.5, 'sl_atr': 4.0, 'max_bars': 48}"
python research/meta_label.py --tf 4h --tp 0.5 --sl 3.0 --bars 24 --oos 2022-01-01   # C walk-forward (~30 min)
python research/meta_label.py --tf 4h --tp 0.5 --sl 3.0 --bars 24 --export           # production model
python research/latest_signals.py --at 2026-09-26T16:00Z                             # reference signals
python research/summarize.py                                                         # funnel table
python research/tp_ladder.py --tf 1h                                                 # TP1/TP2/TP3 study (also --tf 15m)
```
See [`research/README.md`](../research/README.md) for the file map and engine assumptions.

*This is research, not investment advice. Past performance, including out-of-sample backtests, does not guarantee future results. Crypto derivatives can lose more than the margin posted if used with leverage; the strategies above assume 1× notional.*
