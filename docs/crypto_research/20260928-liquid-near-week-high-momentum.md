# 20260928 Liquid Near-Week-High Momentum

## Conclusion

**REJECT.** The preregistered liquid-coin momentum/anchoring hypothesis failed the development gate; 2024-2025 OOS was not consumed.

## Source and hypothesis

Source: Milan Fičura, *Impact of size and volume on cryptocurrency momentum and reversal* (2023), DOI 10.2139/ssrn.4378429.

Hypothesis: among liquid cryptocurrencies, assets closing near their recent weekly high should outperform assets far from that high.

## Pre-registration

- Point-in-time top 50 by lagged trailing-30-day quote volume.
- Frozen ex-ante Binance USD-M USDT perpetual universe listed by 2021-12-31.
- Lookbacks: 7, 14, 28 days; canonical = 7.
- Weekly Monday 00:00 UTC execution, using only completed prior-day data.
- Market-neutral 0.5 gross long / 0.5 gross short.
- Base cost: 10 bps one-way.

## Development evidence

| Lookback | Mean rank IC | HAC p | Net Sharpe | Net return |
|---|---:|---:|---:|---:|
| 7d | 0.0178 | 0.2730 | -1.220 | -48.7% |
| 14d | 0.0209 | 0.2141 | -0.999 | -43.9% |
| 28d | 0.0150 | 0.4592 | -1.134 | -48.2% |

The canonical 7-day factor missed the preregistered IC and significance thresholds and its high-minus-low spread was negative (-0.76% per week before portfolio-cost aggregation). This is the opposite of the intended tradable relationship.

## Decision

Reject without OOS consumption. Counted parameter trials: 3; cumulative trial count: 124.

## Reproduction

`PYTHONPATH=. uv run python scripts/run_crypto_liquid_near_week_high.py --root <BINANCE_UM_PERP_1H_STORE>`
