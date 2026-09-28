# 20260928 DUVOL Crash-Risk Factor

## Conclusion

**REJECT.** The preregistered DUVOL crash-risk hypothesis failed decisively in development; 2024-2025 OOS was not consumed.

## Source and mechanism

Source: Mehak Younus and Muhammad Abubakr Naeem, *Crash Risk and the Cross-Section of Cryptocurrency Returns* (2024), DOI 10.2139/ssrn.4823589.

The source reports lower subsequent returns for crash-prone cryptocurrencies using negative conditional skewness and down-to-up volatility. This test isolated DUVOL. The signal was `-log(sd_down/sd_up)`, so a positive IC would mean lower crash risk predicts higher next-week returns.

## Pre-registration

- 30/60/90-day windows; canonical = 60 days.
- Point-in-time top 50 by lagged 30-day quote volume.
- Weekly Monday-open rebalance, all inputs completed by Sunday.
- 0.5 gross long highest `-DUVOL`, 0.5 gross short lowest.
- 10 bps one-way base costs.

## Development evidence

| Window | Mean rank IC | HAC p | Net Sharpe | Net return |
|---|---:|---:|---:|---:|
| 30d | -0.0570 | 0.000018 | -1.017 | -38.2% |
| 60d | -0.0865 | 1.1e-12 | -1.148 | -39.2% |
| 90d | -0.0761 | 1.7e-7 | -1.093 | -37.2% |

The sign was not merely noisy: it was statistically strong **opposite** the preregistered economic direction across all three windows.

## Decision

Reject without OOS consumption. Counted parameter trials: 3; cumulative trial count: 127.

## Reproduction

`PYTHONPATH=. uv run python scripts/run_crypto_crash_risk_duvol.py --root <BINANCE_UM_PERP_1H_STORE>`
