# 20260928 Abnormal-Volume Disagreement Daily

## Conclusion
**REJECT.** The earlier connector-output loss was resolved with an identical rerun. The signal is statistically real in development, but uneconomic after the preregistered 10 bps one-way cost.

## Source
Garfinkel, Hsiao, and Hu, *Disagreement and returns: The case of cryptocurrencies*, Financial Management 54 (2025), DOI 10.1111/fima.12491.

## Result
The canonical 30-day abnormal-volume proxy achieved mean rank IC **0.0646** with HAC p-value below 1e-18, but net development Sharpe was **-0.405** and total return **-23.0%**. The 7/15/30-day variants all lost materially; the 45-day variant was near flat after costs.

## Decision
Development gate failed; exploratory OOS and sealed confirmation data were not consumed. No new parameter variants were introduced by the rerun, so the original cumulative trial accounting remains **100** at that point in the ledger.

## Reproduction
`uv run python -m scripts.run_crypto_abnormal_volume --root /home/quant/dev/quant/ml4t-data/.data/store/crypto_futures_ohlcv_1h_BINANCE_UM_PERP`
