# 20260928 Bull-Regime Liquid Momentum Long-Only

## Conclusion

**REJECT.** The 30-day BTC-regime variant showed strong development PnL, but the underlying cross-sectional momentum relation failed the preregistered diagnostic and stability gates. OOS was not consumed.

## Sources

- Fieberg, Liedtke & Zaremba, *Cryptocurrency anomalies and economic constraints* (2024), DOI 10.1016/j.irfa.2024.103218.
- Cakici et al., *Machine learning and the cross-section of cryptocurrency returns* (2024), DOI 10.1016/j.irfa.2024.103244.

The mechanism tested was source-driven: liquid-coin momentum restricted to bullish BTC regimes, using only the long winner leg.

## Pre-registration

- Frozen Binance USD-M USDT perpetual universe listed by 2021-12-31.
- Top 30 by lagged trailing-30-day quote volume.
- 30-day asset momentum.
- BTC positive-return regime over 14/30/60 days; canonical = 30.
- Weekly Monday-open rebalance; inputs through Sunday only.
- Long-only top momentum quintile, otherwise cash.
- 10 bps one-way base costs.

## Development evidence

| BTC regime | Active weeks | Rank IC | HAC p | Net Sharpe | Net return | Max DD |
|---|---:|---:|---:|---:|---:|---:|
| 14d | 53 | -0.0266 | 0.366 | 0.259 | -5.5% | -62.1% |
| 30d | 53 | -0.0384 | 0.160 | **1.130** | **+172.6%** | -35.3% |
| 60d | 45 | -0.0353 | 0.239 | 0.098 | -19.8% | -63.5% |

The isolated 30-day portfolio is not promotable: cross-sectional IC was negative, two neighboring preregistered regime windows lost money, 2022 was negative, and drawdown was just beyond the stated threshold. Selecting only the 30-day variant after observing this surface would be post-hoc tuning.

## Decision

Reject without OOS consumption. Counted parameter trials: 3; cumulative count: 133.

## Reproduction

`PYTHONPATH=. uv run python scripts/run_crypto_bull_regime_momentum.py --root <BINANCE_UM_PERP_1H_STORE>`
