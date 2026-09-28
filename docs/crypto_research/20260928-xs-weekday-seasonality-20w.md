# Crypto Research Run - Cross-Sectional Same-Weekday Seasonality

## Conclusion

**REJECT.** The preregistered 20-week same-weekday factor failed development. Canonical 2022-2023 net Sharpe was **-1.267**, total return **-42.46%**, and max drawdown **-43.03%**. Exploratory 2024-2025 OOS was not consumed.

## Source and Hypothesis

Long et al., *Seasonality in the Cross-Section of Cryptocurrency Returns*, Finance Research Letters (2020), DOI 10.1016/j.frl.2020.101566. The tested mechanism was persistence in asset-specific same-weekday returns.

## Pre-Registration

Formation windows were 10, 20, and 25 weeks with 20 weeks canonical. The point-in-time universe was the top 50 eligible Binance USD-M USDT perpetuals by lagged trailing-30-day quote volume. The portfolio was dollar-neutral: long the top signal quintile, short the bottom quintile, 1.0 gross. Signals used completed prior data; execution was current UTC-day open to next-day open. Base friction was 10 bps per unit of actual turnover.

## Signal Diagnostics

| Formation | Mean rank IC | HAC p-value | Raw H-L mean |
| --- | ---: | ---: | ---: |
| 10 weeks | 0.0023 | 0.7403 | 0.0856% |
| **20 weeks** | **0.0139** | **0.0403** | **0.1760%** |
| 25 weeks | 0.0105 | 0.1150 | 0.1550% |

Canonical IC failed the preregistered 0.02 diagnostic threshold.

## Results

| Formation | Net Sharpe | Total return | Max DD | Turnover |
| --- | ---: | ---: | ---: | ---: |
| 10 weeks | -1.910 | -58.64% | -61.38% | 1147.1 |
| **20 weeks** | **-1.267** | **-42.46%** | **-43.03%** | **1154.0** |
| 25 weeks | -1.501 | -46.66% | -48.97% | 1155.4 |

Canonical returns were negative in both development years: -28.06% in 2022 and -20.02% in 2023.

## Methodology and Failure Analysis

The loader observed 262 USDT perpetual symbols. Each date ranked only contemporaneously eligible contracts. Same-weekday rolling means were grouped by symbol and weekday, shifted to exclude the current observation, and required exact historical anchors. Liquidity used only completed prior days. The raw factor spread was positive but too small relative to daily turnover costs.

## Multiple-Testing Audit and Decision

Three preregistered formation-window trials advance the reconciled count from **168 to 171**. DSR/PBO were not computed because the development gate failed before OOS.

**Decision: REJECT**

Reproduction: `uv run python scripts/run_crypto_xs_weekday_seasonality.py --root /home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_ohlcv_1h_BINANCE_UM_PERP`
