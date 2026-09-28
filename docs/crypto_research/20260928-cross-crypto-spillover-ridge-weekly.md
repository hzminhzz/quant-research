# 20260928 Cross-Crypto Spillover Ridge

## Conclusion

**REJECT.** The rolling cross-crypto predictor produced a statistically significant relationship in the opposite direction from the preregistered spillover hypothesis. OOS was not consumed.

## Source

Guo, Sang, Tu & Wang, *Cross-Cryptocurrency Return Predictability*, SSRN 3974583, revised May 13, 2024. The paper reports that lagged returns of other cryptocurrencies predict focal-coin returns and that an OOS long-short portfolio survives costs.

## Pre-registration

- Frozen Binance USD-M USDT perpetual universe listed by 2021-12-31.
- Point-in-time top 50 by lagged 30-day quote volume.
- Fixed predictor set: BTC, ETH, BNB, XRP, ADA, DOGE, LTC, SOL prior-week returns.
- Separate 52-week rolling ridge model per target coin.
- Training-window-only standardization.
- Ridge alpha 0.1 / 1 / 10; canonical = 1.
- Weekly Monday-open market-neutral quintile portfolio.
- 10 bps one-way costs.

## Development evidence

| Ridge alpha | Rank IC | HAC p | Net Sharpe | Net return |
|---|---:|---:|---:|---:|
| 0.1 | -0.0385 | 0.0133 | -1.627 | -47.5% |
| 1.0 | -0.0378 | 0.0157 | -1.776 | -50.0% |
| 10.0 | -0.0357 | 0.0371 | -2.053 | -53.3% |

The negative sign was stable across the full preregistered ridge sensitivity surface. Reversing the strategy after observing that sign is prohibited post-hoc tuning.

## Decision

Reject without OOS consumption. Three new trials; cumulative trial count: 136.

## Reproduction

`PYTHONPATH=. uv run python scripts/run_crypto_cross_spillover_ridge.py --root <BINANCE_UM_PERP_1H_STORE>`
