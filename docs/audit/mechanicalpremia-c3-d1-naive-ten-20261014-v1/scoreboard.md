# C3 daily entry simplification — ten variants (native ML4T)

**Status:** RUNNING; 24/180 native annual/stress cells completed.
**Decision:** Not approved, all years observed; no new OOS. C3 promoted baseline unchanged.
**Model:** H1 and D1 exits, risk splits and next-bar fills fixed. The 10 trials change ONLY daily entry eligibility.
**Accounting:** Annual $100k synthetic price-unit simulations reset independently, not a continuous account. Real CFD spreads, financing, lot mapping and D1 protective stop unqualified.

| Variant | Complete years | D1 closed trades | D1 trade PF | Mean annual return | Mean Sharpe | Positive years | Worst-year DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| SOURCE-US2 | 14/14 | 58 | 8.14 | +2.99% | 0.66 | 10/14 | -7.83% |
| N01-LV-PB35 | 2/14 | 13 | - | +6.14% | 1.61 | 2/2 | -1.66% |
| N02-LV-PB50 | 2/14 | 16 | 315.26 | +5.83% | 1.36 | 2/2 | -1.90% |
| N03-LV-PB80 | 1/14 | 14 | - | +7.56% | 1.30 | 1/1 | -2.45% |
| N04-PB20 | 1/14 | 9 | 3.34 | +5.53% | 0.87 | 1/1 | -5.26% |
| N05-PB35 | 1/14 | 12 | 4.06 | +8.49% | 1.14 | 1/1 | -5.45% |
| N06-PB50 | 1/14 | 14 | 3.88 | +7.64% | 0.96 | 1/1 | -5.45% |
| N07-PB80 | 1/14 | 22 | 3.15 | +6.85% | 0.78 | 1/1 | -6.30% |
| N08-LV-ONLY | 1/14 | 14 | - | +7.56% | 1.30 | 1/1 | -2.45% |
| N09-TREND | 1/14 | 24 | 3.35 | +6.89% | 0.78 | 1/1 | -6.19% |
| N10-VOLPB20 | 1/14 | 5 | - | +5.89% | 1.64 | 1/1 | -1.60% |

**Do not rank incomplete trials by these values.** See scoreboard.json for explicit missing cells, sample sizes and native per-year evidence.
**Fees:** 1bp commission + 2bps slippage per side; 2x tests are preregistered in 2021/2024/2025/2026.
**Baseline:** SOURCE-US2 combined portfolio; baseline D1 closed-trade subset extracted from native trades.parquet, NOT standalone D1-only where position sizes differ.
**Interpretation:** If a relaxed rule produces more signals but unchanged native D1 entries, position occupancy or the unchanged exit rule is the bottleneck.
