# 20260928 Price-Path Continuity Weekly

## Conclusion
**REJECT.** The preregistered continuation direction failed decisively in development; OOS was not consumed.

## Source
Woong Bae Kim, *Price Path Continuity and the Cross-Section of Cryptocurrency Returns* (SSRN 6871159, 2026-06-01).

## Hypothesis and mechanism
Smoothly accumulated prior returns were expected to continue cross-sectionally. The fixed proxy was prior cumulative return multiplied by path efficiency.

## Universe and execution
Frozen ex-ante Binance USD-M USDT perpetuals listed by 2021-12-31. Each Monday, top 50 by lagged trailing-30-day quote volume. Inputs ended Sunday; execution was Monday open; holding period one week. Base cost: 10 bps one-way.

## Results
| Lookback | Rank IC | HAC p | Spread | Net Sharpe | Total return |
|---:|---:|---:|---:|---:|---:|
| 7d | -0.0567 | 0.0022 | -0.44% | -0.898 | -35.8% |
| 14d canonical | -0.0706 | 0.0019 | -1.23% | -1.543 | -56.4% |
| 28d | -0.0541 | 0.0101 | -0.78% | -1.092 | -42.4% |

The relationship was statistically significant in the opposite direction for all three preregistered windows, so the development gate failed.

## Multiple-testing audit
Three new parameter trials. Cumulative crypto strategy parameter trials: **139**. DSR/PBO were not meaningful because OOS was not consumed.

## Reproduction
`uv run python -m scripts.run_crypto_price_path_continuity --root /home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_ohlcv_1h_BINANCE_UM_PERP`
