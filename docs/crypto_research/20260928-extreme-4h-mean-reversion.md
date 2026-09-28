# 20260928 Extreme 4h Mean Reversion

## Conclusion
**REJECT.** The broad-perpetual 4h reversal rule failed decisively in development; exploratory OOS was not consumed.

## Sources
Primary: Giacomo De Nicola, *On the Intraday Behavior of Bitcoin*, Ledger 6 (2021), DOI 10.5195/ledger.2021.213. Supporting mechanism check: Kitron and Wengrowicz, *Short-horizon mean reversion in cryptocurrency markets: a matched cross-market measurement* (2026).

## Pre-registered design
Binance USD-M USDT perpetuals listed by 2021-12-31. Four-hour bars are built from complete 1h bars. At each 4h boundary, retain the top 20 contracts by lagged trailing-30-day quote volume. Use the previous completed 4h return divided by trailing 30-day 4h volatility; when |z| exceeds the fixed threshold, trade against the move for the next 4h bar. Thresholds: 1.0/1.5/2.0, canonical 1.5. Base cost: 10 bps one-way.

## Development results
| Threshold | Net Sharpe | Total return | Max DD | Events |
|---:|---:|---:|---:|---:|
| 1.0 | -2.505 | -99.86% | -99.89% | 17,939 |
| 1.5 canonical | -1.640 | -99.60% | -99.69% | 8,726 |
| 2.0 | -1.368 | -99.02% | -99.40% | 4,561 |

The rule is not merely weak: transaction intensity plus adverse post-shock behavior makes it economically unusable under the fixed cost model.

## Multiple-testing audit
Three new parameter trials; cumulative strategy parameter trials: **145**. DSR/PBO were not meaningful because OOS was not consumed.

## Reproduction
`PYTHONPATH=. uv run python scripts/run_crypto_extreme_4h_reversion.py --root /home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_ohlcv_1h_BINANCE_UM_PERP`
