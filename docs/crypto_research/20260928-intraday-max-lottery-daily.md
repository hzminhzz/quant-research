# 20260928 Intraday MAX Lottery Effect

## Conclusion

**REJECT.** The factor was statistically strong, but the daily implementation was not economically tradeable after preregistered costs. OOS remained sealed.

## Source

*Intraday lottery demands in cryptocurrency market*, Studies in Economics and Finance (2025), DOI 10.1108/SEF-07-2024-0461.

The paper reports that extreme positive intraday returns proxy lottery demand and predict lower subsequent returns.

## Pre-registration

- Frozen Binance USD-M USDT perpetual universe listed by 2021-12-31.
- Daily 00:00 UTC rebalance; feature uses only completed hourly bars through 23:00 UTC.
- Top 50 by lagged 30-day quote volume.
- Signal = negative maximum hourly return over 12/24/48h; canonical = 24h.
- Market-neutral long low-MAX / short high-MAX.
- 10 bps one-way base costs.

## Development diagnostics

| Lookback | Rank IC | HAC p | Net Sharpe | Net return | Turnover |
|---|---:|---:|---:|---:|---:|
| 12h | 0.0804 | 1.9e-29 | -0.748 | -39.0% | 895.4 |
| 24h | 0.0953 | 1.9e-35 | -0.515 | -30.6% | 836.4 |
| 48h | 0.1037 | 3.9e-38 | 0.553 | 25.8% | 569.9 |

The predictive relationship is real in development, but turnover/cost drag is decisive. The positive 48h neighbor is retained only as evidence; selecting it after observing the surface would be post-hoc tuning.

## Decision

Reject without OOS consumption. Counted parameter trials: 3; cumulative count: 130.

## Reproduction

`PYTHONPATH=. uv run python scripts/run_crypto_intraday_max.py --root <BINANCE_UM_PERP_1H_STORE>`
