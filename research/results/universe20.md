# Universe expansion to 20 coins (October 2026): FAIL, stay on 10

Question: can strategy C (MLR-4H) cover 20 coins instead of 10 without hurting the channel?

Fixed before any result:

* **New coins:** USDT-M perpetuals on a coin (no stablecoin or index), on Binance futures before
  2021-01-01 and still trading, top 10 by median daily futures volume Oct 2025 – Sep 2026 (61 eligible):
  ZEC, NEAR, BCH, FIL, AAVE, UNI, LTC, XLM, TRX, DASH. Spot candles from the Binance data portal, like
  the original 10.
* **Method:** the production recipe unchanged (`meta_label.py --universe 20`): quarterly walk-forward
  from 2022-01, threshold = 95th percentile of the trailing year's in-sample probabilities, at most 5
  C signals per candle. A/B stay on the original 10. Live lifecycle and session (`universe_study.py`).
* **Pass criteria:** (1) new 10 coins win ≥ 85 %, PF ≥ 1.3, and PF ≥ 1.2 in 2025+; (2) C on the
  original 10 within 0.1 PF of today's model; (3) whole channel PF ≥ today's and max drop ≤ 10 %.

Result: all three fail. The new coins are near break-even since 2025, and sharing the model with them
weakens C on the original 10 (PF 1.72 → 1.39). The channel's max drop would rise from 8.5 % to 19.3 %.
No variant was tried after seeing the result.

```

=== 2022-01 → now (1746 days), published signals ===
 today (C on 10)
  all strategies                      3705 (2.12/day) · win  89.2% · PF 1.48 · growth  +66.6% · max drop  8.5% · losses in a row 11
  A+B                                 1735 (0.99/day) · win  88.9% · PF 1.24 · growth   +4.3% · max drop 13.6% · losses in a row 11
  C on the original 10                1970 (1.13/day) · win  89.5% · PF 1.72 · growth  +59.8% · max drop  6.6% · losses in a row 8
 new (C on 20)
  all strategies                      4586 (2.63/day) · win  87.7% · PF 1.28 · growth  +29.6% · max drop 19.3% · losses in a row 9
  A+B                                 1735 (0.99/day) · win  88.9% · PF 1.24 · growth   +4.3% · max drop 13.6% · losses in a row 11
  C on the original 10                1393 (0.80/day) · win  87.2% · PF 1.39 · growth  +13.4% · max drop  7.0% · losses in a row 6
  C on the new 10                     1458 (0.84/day) · win  86.9% · PF 1.23 · growth   +9.6% · max drop 11.2% · losses in a row 7

=== 2022–2024 (1096 days), published signals ===
 today (C on 10)
  all strategies                      2244 (2.05/day) · win  89.5% · PF 1.52 · growth  +35.4% · max drop  8.5% · losses in a row 8
  A+B                                 1073 (0.98/day) · win  89.8% · PF 1.38 · growth   +7.9% · max drop  9.4% · losses in a row 5
  C on the original 10                1171 (1.07/day) · win  89.2% · PF 1.64 · growth  +25.5% · max drop  6.6% · losses in a row 6
 new (C on 20)
  all strategies                      2774 (2.53/day) · win  88.5% · PF 1.43 · growth  +30.9% · max drop 17.2% · losses in a row 8
  A+B                                 1073 (0.98/day) · win  89.8% · PF 1.38 · growth   +7.9% · max drop  9.4% · losses in a row 5
  C on the original 10                 846 (0.77/day) · win  87.7% · PF 1.52 · growth   +9.8% · max drop  6.7% · losses in a row 6
  C on the new 10                      855 (0.78/day) · win  87.6% · PF 1.40 · growth  +10.4% · max drop  5.9% · losses in a row 7

=== 2025 → now (650 days), published signals ===
 today (C on 10)
  all strategies                      1461 (2.25/day) · win  88.8% · PF 1.42 · growth  +23.0% · max drop  7.0% · losses in a row 11
  A+B                                  662 (1.02/day) · win  87.5% · PF 1.03 · growth   -3.4% · max drop  5.0% · losses in a row 10
  C on the original 10                 799 (1.23/day) · win  90.0% · PF 1.87 · growth  +27.3% · max drop  4.0% · losses in a row 8
 new (C on 20)
  all strategies                      1812 (2.79/day) · win  86.6% · PF 1.08 · growth   -1.0% · max drop 17.5% · losses in a row 9
  A+B                                  662 (1.02/day) · win  87.5% · PF 1.03 · growth   -3.4% · max drop  5.0% · losses in a row 10
  C on the original 10                 547 (0.84/day) · win  86.3% · PF 1.17 · growth   +3.2% · max drop  7.0% · losses in a row 6
  C on the new 10                      603 (0.93/day) · win  85.9% · PF 1.05 · growth   -0.8% · max drop 11.2% · losses in a row 3

=== new coins, C only, published, 2022-01 → now (information only: coins are not picked by result) ===
  ZECUSDT                              144 (0.08/day) · win  86.8% · PF 1.16 · growth   +0.5% · max drop  1.7% · losses in a row 2
  NEARUSDT                             179 (0.10/day) · win  91.6% · PF 2.14 · growth   +6.8% · max drop  1.5% · losses in a row 2
  BCHUSDT                              148 (0.08/day) · win  87.8% · PF 1.31 · growth   +1.7% · max drop  1.6% · losses in a row 2
  FILUSDT                              170 (0.10/day) · win  86.5% · PF 1.53 · growth   +3.1% · max drop  1.9% · losses in a row 2
  AAVEUSDT                             181 (0.10/day) · win  89.0% · PF 1.18 · growth   +1.9% · max drop  3.4% · losses in a row 2
  UNIUSDT                              155 (0.09/day) · win  83.9% · PF 0.96 · growth   -1.7% · max drop  3.0% · losses in a row 3
  LTCUSDT                              162 (0.09/day) · win  86.4% · PF 1.09 · growth   +0.5% · max drop  2.8% · losses in a row 3
  XLMUSDT                              130 (0.07/day) · win  89.2% · PF 1.29 · growth   +1.1% · max drop  2.4% · losses in a row 2
  TRXUSDT                               50 (0.03/day) · win  70.0% · PF 0.38 · growth   -3.5% · max drop  4.1% · losses in a row 3
  DASHUSDT                             139 (0.08/day) · win  85.6% · PF 1.07 · growth   -0.8% · max drop  3.5% · losses in a row 2

=== open signals before TP1 (published), 2022-01 → now ===
  today (C on 10)    most at once 21 (99th pct 10; 10 or more 1.2% of 4H checks) · same direction max 21 (99th pct 9; 12 or more on 12 days)
  new (C on 20)      most at once 21 (99th pct 13; 10 or more 3.2% of 4H checks) · same direction max 21 (99th pct 12; 12 or more on 49 days)

=== quiet days (published), 2022-01 → now ===
  today (C on 10)    days without a signal 44% · quiet spells of 3+ days: 87 (one every 20 days) · longest 15 days
  new (C on 20)      days without a signal 43% · quiet spells of 3+ days: 88 (one every 20 days) · longest 9 days

=== pass criteria (fixed before the test) ===
  FAIL  1. new 10 coins: win 86.9% >= 85%, PF 1.23 >= 1.3, 2025+ PF 1.05 >= 1.2
  FAIL  2. original 10 coins: C PF 1.39 vs today 1.72 (allowed down to 1.62)
  FAIL  3. whole channel: PF 1.28 vs today 1.48; max drop 19.3% <= 10%

VERDICT: FAIL: stay on 10 coins
```
