# Improvement log

Each change is tested the same way: choose on older data, judge on newer data it never saw.
Changes that only help in-sample are rejected.

## 2026-11-13 · Swing trading: blend all strategies instead of picking one

| 2022 → Nov 2026 (out-of-sample) | CAGR | Sharpe | Max drawdown |
|---|---|---|---|
| Buy and hold | 9.9% | 0.78 | −19.5% |
| Old: single best in-sample strategy (low_vol_rotation) | 6.0% | 0.61 | −18.0% |
| Re-pick the best strategy every month (1–3 yr lookback) | −0.3% to 11.5% | 0.09–0.65 | −26% to −38% |
| Re-pick the best 3 every month | 5.3–8.6% | 0.54–0.82 | −10% to −13% |
| Equal blend of all 16 strategies | 6.3% | 0.93 | −5.3% |
| **New: blend scaled 1.5×, capped at 100% invested** | **9.2%** | **0.92** | **−7.8%** |

Lesson: chasing the recent winner is unstable; diversifying across strategies that make money at
different times is what held up. The blend is only ~55% invested on average, so scaling it 1.5×
(no borrowing) brings returns close to buy and hold with less than half the drawdown.
Adopted: `blend_all_scaled` is now the traded swing strategy.

## 2026-11-13 · Day trading: skip trend days

The VWAP-reversion bot fades big moves, which loses on days that trend in one direction.
Filter: no new entries when the day's efficiency ratio (net move since the open ÷ total distance
travelled) is 0.1 or more. Six months of minute data, 8 stocks, 2 bps per side:

| Avg daily P&L (bps) | Before Aug 27 | From Aug 27 (out-of-sample) |
|---|---|---|
| Old (no filter) | −2.95 | −4.23 |
| **New (trend-day filter)** | **+3.45** | **−2.42** |
| Rejected: wait for the price to turn before entering | +0.76 | −4.75 |

Adopted, but still a loss out-of-sample: the bot is still not profitable after costs.

## 2026-11-13 · Fix: separate the two traders

The swing trader would have closed the day bot's positions, and both traded QQQ. The swing trader now
only touches its own universe, and the bot skips any symbol in it.

## 2026-11-13 · Rejected: a bigger universe (24 ETFs instead of 12)

Added real estate, commodities, inflation-linked, corporate and high-yield bonds, more sectors, silver, Japan.
Blend Sharpe fell in both periods (1.03 → 0.95 before 2022; 0.92 → 0.78 after) and the out-of-sample
drawdown deepened (−7.8% → −10.0%). Many additions move with assets already held. Kept the 12.

## 2026-11-13 · Added: live scorecard (`python -m trading.scorecard`)

Compares the account's live results with the backtest's expectations and flags drift. Rule: when
live results fall outside the normal range, cut size or stop; don't re-tune on the same data.
