# Universe expansion to 15 coins (October 2026): FAIL, stay on 10

Follow-up to `universe20.md` during the first quiet days after launch: would 5 extra coins work better
than 10? Same method and pass criteria as the 20-coin study; the 5 coins are the top 5 of the same
volume ranking (ZEC, NEAR, BCH, FIL, AAVE), not picked by result (`meta_label.py --universe 15`,
`universe_study.py --universe 15`).

Result: two of three criteria fail. Over the whole test the channel grows a little faster (more
signals) but with a lower profit factor and a deeper fall; since 2025 the new coins are near break-even
(PF 1.14) and C on the original 10 drops from PF 1.87 to 1.40, so the channel's 2025+ growth falls from
+23 % to +13 %. Days without a signal stay at 43–44 %: quiet spells are market-wide.

```

=== 2022-01 → now (1746 days), published signals ===
 today (C on 10)
  all strategies                      3705 (2.12/day) · win  89.2% · PF 1.48 · growth  +66.6% · max drop  8.5% · losses in a row 11
  A+B                                 1735 (0.99/day) · win  88.9% · PF 1.24 · growth   +4.3% · max drop 13.6% · losses in a row 11
  C on the original 10                1970 (1.13/day) · win  89.5% · PF 1.72 · growth  +59.8% · max drop  6.6% · losses in a row 8
 new (C on 15)
  all strategies                      4319 (2.47/day) · win  88.8% · PF 1.44 · growth  +76.2% · max drop 10.6% · losses in a row 10
  A+B                                 1735 (0.99/day) · win  88.9% · PF 1.24 · growth   +4.3% · max drop 13.6% · losses in a row 11
  C on the original 10                1708 (0.98/day) · win  89.3% · PF 1.74 · growth  +49.4% · max drop  5.7% · losses in a row 6
  C on the new 5                       876 (0.50/day) · win  87.4% · PF 1.35 · growth  +13.1% · max drop  3.7% · losses in a row 5

=== 2022–2024 (1096 days), published signals ===
 today (C on 10)
  all strategies                      2244 (2.05/day) · win  89.5% · PF 1.52 · growth  +35.4% · max drop  8.5% · losses in a row 8
  A+B                                 1073 (0.98/day) · win  89.8% · PF 1.38 · growth   +7.9% · max drop  9.4% · losses in a row 5
  C on the original 10                1171 (1.07/day) · win  89.2% · PF 1.64 · growth  +25.5% · max drop  6.6% · losses in a row 6
 new (C on 15)
  all strategies                      2630 (2.40/day) · win  89.7% · PF 1.62 · growth  +55.6% · max drop  7.6% · losses in a row 9
  A+B                                 1073 (0.98/day) · win  89.8% · PF 1.38 · growth   +7.9% · max drop  9.4% · losses in a row 5
  C on the original 10                1046 (0.95/day) · win  90.2% · PF 1.98 · growth  +32.0% · max drop  4.7% · losses in a row 5
  C on the new 5                       511 (0.47/day) · win  88.1% · PF 1.49 · growth   +9.3% · max drop  3.7% · losses in a row 5

=== 2025 → now (650 days), published signals ===
 today (C on 10)
  all strategies                      1461 (2.25/day) · win  88.8% · PF 1.42 · growth  +23.0% · max drop  7.0% · losses in a row 11
  A+B                                  662 (1.02/day) · win  87.5% · PF 1.03 · growth   -3.4% · max drop  5.0% · losses in a row 10
  C on the original 10                 799 (1.23/day) · win  90.0% · PF 1.87 · growth  +27.3% · max drop  4.0% · losses in a row 8
 new (C on 15)
  all strategies                      1689 (2.60/day) · win  87.4% · PF 1.18 · growth  +13.2% · max drop 10.6% · losses in a row 10
  A+B                                  662 (1.02/day) · win  87.5% · PF 1.03 · growth   -3.4% · max drop  5.0% · losses in a row 10
  C on the original 10                 662 (1.02/day) · win  87.9% · PF 1.40 · growth  +13.2% · max drop  5.7% · losses in a row 6
  C on the new 5                       365 (0.56/day) · win  86.6% · PF 1.14 · growth   +3.5% · max drop  3.3% · losses in a row 2

=== new coins, C only, published, 2022-01 → now (information only: coins are not picked by result) ===
  ZECUSDT                              138 (0.08/day) · win  79.7% · PF 0.88 · growth   -3.0% · max drop  4.8% · losses in a row 2
  NEARUSDT                             214 (0.12/day) · win  92.1% · PF 2.48 · growth   +8.9% · max drop  1.0% · losses in a row 2
  BCHUSDT                              165 (0.09/day) · win  86.7% · PF 1.15 · growth   +1.4% · max drop  2.2% · losses in a row 2
  FILUSDT                              160 (0.09/day) · win  87.5% · PF 1.39 · growth   +2.4% · max drop  1.4% · losses in a row 2
  AAVEUSDT                             199 (0.11/day) · win  88.4% · PF 1.25 · growth   +3.1% · max drop  2.5% · losses in a row 2

=== open signals before TP1 (published), 2022-01 → now ===
  today (C on 10)    most at once 21 (99th pct 10; 10 or more 1.2% of 4H checks) · same direction max 21 (99th pct 9; 12 or more on 12 days)
  new (C on 15)      most at once 21 (99th pct 11; 10 or more 2.3% of 4H checks) · same direction max 21 (99th pct 10; 12 or more on 27 days)

=== quiet days (published), 2022-01 → now ===
  today (C on 10)    days without a signal 44% · quiet spells of 3+ days: 87 (one every 20 days) · longest 15 days
  new (C on 15)      days without a signal 43% · quiet spells of 3+ days: 95 (one every 18 days) · longest 9 days

=== pass criteria (fixed before the test) ===
  FAIL  1. new 5 coins: win 87.4% >= 85%, PF 1.35 >= 1.3, 2025+ PF 1.14 >= 1.2
  PASS  2. original 10 coins: C PF 1.74 vs today 1.72 (allowed down to 1.62)
  FAIL  3. whole channel: PF 1.44 vs today 1.48; max drop 10.6% <= 10%

VERDICT: FAIL: stay on 10 coins
```
