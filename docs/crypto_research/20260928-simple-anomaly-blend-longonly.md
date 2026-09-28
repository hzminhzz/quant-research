# 20260928 Simple Anomaly Blend — Long Only

## Conclusion
**REJECT.** The source-inspired blend of momentum, past market-adjusted alpha and illiquidity failed the development gate; exploratory OOS was not consumed.

## Source
Cakici, Shahzad, Będowska-Sójka, and Zaremba, *Machine learning and the cross-section of cryptocurrency returns*, International Review of Financial Analysis 94 (2024), 103244.

## Design
Point-in-time Binance USD-M USDT perpetual universe. Each Monday, top 50 by lagged trailing-30-day quote volume. Signal = equal-weight cross-sectional rank blend of momentum, market-adjusted past return, and Amihud illiquidity. Long-only top quintile; Monday-open to Monday-open; 10 bps one-way base costs. Preregistered lookbacks: 14/30/60 days, 30-day canonical.

## Development results
| Lookback | Rank IC | HAC p | Net Sharpe | Total return | Max DD |
|---:|---:|---:|---:|---:|---:|
| 14d | -0.0683 | 0.0023 | -0.597 | -84.2% | -92.4% |
| 30d canonical | -0.0638 | 0.0020 | -0.484 | -78.5% | -88.3% |
| 60d | -0.0918 | 0.000024 | -0.818 | -86.7% | -91.6% |

The rank IC was significantly opposite the preregistered direction. This is a clean rejection, not a candidate for sign-flipping after observation.

## Multiple-testing audit
Three new trials; cumulative strategy parameter trials: **142**. DSR/PBO not applicable because OOS was not consumed.

## Reproduction
`PYTHONPATH=. uv run python scripts/run_crypto_simple_anomaly_blend.py --root /home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_ohlcv_1h_BINANCE_UM_PERP`
